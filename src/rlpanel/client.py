"""Eğitim tarafı istemcisi.

Temel kural: panel yüzünden eğitim asla çökmez veya yavaşlamaz. Ağ işi ayrı bir
thread'de yapılır; hatalar yutulup tek satır uyarıya çevrilir. Sunucuya
ulaşılamazsa veriler `.rlpanel_buffer.jsonl` dosyasına yazılır ve bağlantı
gelince otomatik gönderilir (dosya panele elle de yüklenebilir).
"""
from __future__ import annotations

import atexit
import json
import math
import os
import re
import socket
import sys
import threading
import time
import traceback
import urllib.error
from pathlib import Path
from typing import Any, Mapping

from rlpanel import http, launcher, logcapture
from rlpanel.jsonutil import clean_json

RECONNECT_SECONDS = 10.0
HEARTBEAT_SECONDS = 10.0
MAX_METRICS_PER_BATCH = 5000
MAX_LOGS_PER_BATCH = 2000


def _warn(message: str) -> None:
    try:
        sys.__stderr__.write(f"[rlpanel] {message}\n")
        sys.__stderr__.flush()
    except Exception:
        pass


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    return clean_json(json.loads(json.dumps(value, default=str)))


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "run"


class Panel:
    """Bir eğitim run'ını panele bağlar."""

    def __init__(self, project: str, run: str, *, config: Mapping | None = None, seed: int | None = None,
                 total_steps: int | None = None, server: str | None = None, run_dir: str | Path | None = None,
                 open_browser: bool | None = None, capture_logs: bool = True, flush_interval: float = 1.0) -> None:
        self.project, self.name = str(project), str(run)
        self.run_id: int | None = None
        self.disabled = os.environ.get("RLPANEL_DISABLE") == "1"
        self._explicit_server = server or os.environ.get("RLPANEL_SERVER")
        self._server: str | None = None
        self._create = {"project": self.project, "name": self.name, "seed": seed, "host": socket.gethostname(),
                        "config": _jsonable(config), "total_steps": total_steps}
        self._open_browser = os.environ.get("RLPANEL_NO_BROWSER") != "1" if open_browser is None else open_browser
        base = Path(run_dir) if run_dir is not None else Path.cwd() / ".rlpanel" / _safe(f"{self.project}-{self.name}")
        self.buffer_path = base / ".rlpanel_buffer.jsonl"
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._metrics: list[list] = []
        self._logs: list[list] = []
        self._pending: dict[str, Any] = {}
        self._results: dict[str, Any] = {}
        self._online = False
        self._last_connect_try = float("-inf")
        self._last_sent = 0.0
        self._warned_offline = False
        self._finished = False
        self._stop = threading.Event()
        self._flush_interval = flush_interval
        self._capture = capture_logs
        self._thread: threading.Thread | None = None
        self._hook = None
        self._prev_excepthook = None
        if self.disabled:
            return
        self._flush_safe(force=True)  # sunucuyu bul/başlat, run'ı oluştur
        if capture_logs:
            logcapture.set_sink(self.log_text)
        self._install_hooks()
        self._thread = threading.Thread(target=self._loop, name="rlpanel-flush", daemon=True)
        self._thread.start()

    @property
    def url(self) -> str | None:
        if self._server is None or self.run_id is None:
            return None
        return f"{self._server}/#/run/{self.run_id}"

    @property
    def config(self) -> dict | None:
        return self._create.get("config")

    # ---- genel API ----
    def log(self, metrics: Mapping[str, Any], step: int) -> None:
        if self.disabled or self._finished:
            return
        now = time.time()
        rows = []
        for key, value in metrics.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                rows.append([str(key), int(step), number, now])
        if rows:
            with self._lock:
                self._metrics.extend(rows)

    def log_text(self, line: str, level: str = "INFO") -> None:
        if self.disabled or self._finished:
            return
        with self._lock:
            self._logs.append([time.time(), str(level), str(line)])

    def progress(self, current_step: int, total_steps: int | None = None) -> None:
        if self.disabled:
            return
        with self._lock:
            self._pending["current_step"] = int(current_step)
            if total_steps is not None:
                self._pending["total_steps"] = int(total_steps)
                self._create["total_steps"] = int(total_steps)

    def set_config(self, config: Mapping) -> None:
        if self.disabled:
            return
        cleaned = _jsonable(dict(config))
        with self._lock:
            self._create["config"] = cleaned
            self._pending["config"] = cleaned

    def result(self, results: Mapping) -> None:
        if self.disabled:
            return
        with self._lock:
            self._results.update(_jsonable(dict(results)))
            self._pending["results"] = dict(self._results)

    def finish(self, status: str = "finished", timeout: float = 5.0) -> None:
        if self.disabled or self._finished:
            return
        self._finished = True
        with self._lock:
            self._pending["status"] = status
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)
        if self._capture:
            logcapture.clear_sink(self.log_text)
        self._flush_safe(force=True, drain=True)
        self._restore_hooks()

    def __enter__(self) -> "Panel":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.finish("finished")
        elif issubclass(exc_type, KeyboardInterrupt):
            self.finish("stopped")
        else:
            self.log_text("".join(traceback.format_exception(exc_type, exc, tb)).rstrip(), "ERROR")
            self.finish("crashed")
        return False

    # ---- kancalar ----
    def _install_hooks(self) -> None:
        self._prev_excepthook = sys.excepthook

        def hook(exc_type, exc, tb):
            try:
                self.__exit__(exc_type, exc, tb)
            except Exception:
                pass
            (self._prev_excepthook or sys.__excepthook__)(exc_type, exc, tb)

        self._hook = hook
        sys.excepthook = hook
        atexit.register(self._atexit)

    def _restore_hooks(self) -> None:
        if self._hook is not None and sys.excepthook is self._hook:
            sys.excepthook = self._prev_excepthook or sys.__excepthook__
        try:
            atexit.unregister(self._atexit)
        except Exception:
            pass

    def _atexit(self) -> None:
        self.finish("finished")

    # ---- gönderim ----
    def _loop(self) -> None:
        while not self._stop.wait(self._flush_interval):
            self._flush_safe()

    def _flush_safe(self, force: bool = False, drain: bool = False) -> None:
        try:
            with self._send_lock:
                for _ in range(100 if drain else 1):
                    if not self._flush(force):
                        break
        except Exception as exc:  # hiçbir koşulda eğitime sızmasın
            _warn(f"beklenmeyen hata: {exc!r}")

    def _take(self) -> dict | None:
        with self._lock:
            if not (self._metrics or self._logs or self._pending):
                return None
            batch = {"metrics": self._metrics[:MAX_METRICS_PER_BATCH], "logs": self._logs[:MAX_LOGS_PER_BATCH],
                     **self._pending}
            del self._metrics[:MAX_METRICS_PER_BATCH]
            del self._logs[:MAX_LOGS_PER_BATCH]
            self._pending = {}
            return batch

    def _flush(self, force: bool = False) -> bool:
        """Bir paket gönderir; gönderilecek daha fazla veri kaldıysa True döner."""
        if not self._online:
            self._reconnect(force)
        batch = self._take()
        if batch is None:
            if self._online and time.monotonic() - self._last_sent >= HEARTBEAT_SECONDS:
                self._send({"metrics": [], "logs": []})
            return False
        if self._online:
            self._send(batch)
        else:
            self._buffer(batch)
        with self._lock:
            return bool(self._metrics or self._logs)

    def _reconnect(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_connect_try < RECONNECT_SECONDS:
            return
        self._last_connect_try = now
        try:
            if self._explicit_server:
                target = self._explicit_server.rstrip("/")
                url, started = (target, False) if launcher.health(target) else (None, False)
            else:
                url, started = launcher.ensure_server()
            if url is None:
                return
            if self.run_id is not None:
                try:
                    http.get_json(f"{url}/api/runs/{self.run_id}")
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:
                        raise
                    self.run_id = None
            if self.run_id is None:
                self.run_id = int(http.post_json(f"{url}/api/runs", self._create)["id"])
            self._server, self._online, self._warned_offline = url, True, False
            if started and self._open_browser:
                launcher.open_browser(self.url)
            self._replay_buffer()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._online = False
            if not self._warned_offline:
                _warn(f"panel sunucusuna bağlanılamadı: {exc}")

    def _send(self, batch: dict) -> None:
        try:
            http.post_json(f"{self._server}/api/runs/{self.run_id}/batch", batch)
            self._last_sent = time.monotonic()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                self.run_id, self._online = None, False
                self._buffer(batch)
            else:
                _warn(f"sunucu paketi reddetti (HTTP {exc.code}); paket atlandı")
        except OSError:
            self._online = False
            self._buffer(batch)

    def _buffer(self, batch: dict) -> None:
        try:
            self.buffer_path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not self.buffer_path.exists() or self.buffer_path.stat().st_size == 0
            with open(self.buffer_path, "a", encoding="utf-8") as handle:
                if fresh:
                    handle.write(json.dumps({"op": "create", **self._create}, ensure_ascii=False) + "\n")
                handle.write(json.dumps({"op": "batch", "batch": batch}, ensure_ascii=False, default=str) + "\n")
        except OSError as exc:
            _warn(f"yedek dosyaya yazılamadı ({exc}); paket atlandı")
            return
        if not self._warned_offline:
            self._warned_offline = True
            _warn(f"panel sunucusuna ulaşılamıyor; veriler {self.buffer_path} dosyasında biriktiriliyor")

    def _replay_buffer(self) -> None:
        path = self.buffer_path
        if not path.exists():
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        remaining: list[str] = []
        for index, line in enumerate(lines):
            try:
                op = json.loads(line)
            except json.JSONDecodeError:
                continue
            if op.get("op") != "batch":
                continue
            try:
                http.post_json(f"{self._server}/api/runs/{self.run_id}/batch", op["batch"])
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    continue  # bu paket hiçbir zaman kabul edilmeyecek; atla
                self._online, self.run_id, remaining = False, None, lines[index:]
                break
            except (OSError, ValueError):
                self._online, remaining = False, lines[index:]
                break
        if remaining:
            header = json.dumps({"op": "create", **self._create}, ensure_ascii=False)
            path.write_text("\n".join([header, *remaining]) + "\n", encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
