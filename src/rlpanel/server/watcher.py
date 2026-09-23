"""Klasör izleme: SB3 progress.csv / tfevents / results.json dosyalarını artımlı okur.

Her dosyanın klasörü bir run olur (run adı = klasör adı, proje = üst klasörün adı).
Ofsetler bellekte tutulur; sunucu yeniden başlarsa run'ın metrikleri silinip baştan okunur.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rlpanel.server.importers import parse_progress_csv, parse_tfevents
from rlpanel.server.store import Store

log = logging.getLogger("rlpanel.watcher")


@dataclass
class _CsvState:
    header: bytes | None = None
    offset: int = 0


@dataclass
class _Tracked:
    run_id: int
    csv: dict = field(default_factory=dict)          # Path -> _CsvState
    tb_signature: dict = field(default_factory=dict)  # Path -> (size, mtime)
    tb_last_step: dict = field(default_factory=dict)  # Path -> {key: step}
    results_mtime: float | None = None
    newest: float = 0.0
    max_step: int = 0
    status: str | None = None
    pending: list = field(default_factory=list)
    reset: bool = False
    results_changed: bool = False


def _kind(name: str) -> str | None:
    if name == "progress.csv":
        return "csv"
    if name.startswith("events.out.tfevents"):
        return "tb"
    if name == "results.json":
        return "results"
    return None


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class FolderWatcher:
    def __init__(self, store: Store, publish: Callable[[dict], None], *, interval: float = 2.0,
                 state_file: str | Path | None = None, active_window: float = 60.0) -> None:
        self.store, self.publish, self.interval = store, publish, interval
        self.active_window = active_window
        self.state_file = Path(state_file) if state_file else None
        self._roots: list[Path] = []
        self._runs: dict[Path, _Tracked] = {}
        self._lock = threading.Lock()
        self._scan_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._load_state()

    # ---- kökler ----
    @property
    def roots(self) -> list[str]:
        with self._lock:
            return [str(p) for p in self._roots]

    def add(self, path: str | Path) -> str:
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"klasör bulunamadı: {root}")
        with self._lock:
            if root not in self._roots:
                self._roots.append(root)
                self._save_state()
        return str(root)

    def remove(self, path: str | Path) -> bool:
        root = Path(path).expanduser().resolve()
        with self._lock:
            if root not in self._roots:
                return False
            self._roots.remove(root)
            self._save_state()
        with self._scan_lock:
            self._runs = {d: t for d, t in self._runs.items() if not _is_under(d, root)}
        return True

    def _load_state(self) -> None:
        if not self.state_file or not self.state_file.exists():
            return
        try:
            saved = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._roots = [Path(p) for p in saved if Path(p).is_dir()]

    def _save_state(self) -> None:
        if not self.state_file:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps([str(p) for p in self._roots], ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("izleme listesi kaydedilemedi: %s", exc)

    # ---- thread ----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="rlpanel-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while True:
            try:
                self.scan_once()
            except Exception:
                log.exception("klasör taraması başarısız")
            if self._stop.wait(self.interval):
                return

    # ---- tarama ----
    def scan_once(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._scan_lock:
            with self._lock:
                roots = list(self._roots)
            for root in roots:
                if not root.is_dir():
                    continue
                for path in sorted(root.rglob("*")):
                    kind = _kind(path.name)
                    if kind is None or not path.is_file():
                        continue
                    if kind == "tb" and (path.parent / "progress.csv").exists():
                        continue
                    try:
                        tracked = self._tracked(path.parent)
                        self._process(path, kind, tracked)
                        tracked.newest = max(tracked.newest, path.stat().st_mtime)
                    except OSError as exc:
                        log.warning("%s okunamadı: %s", path, exc)
            for tracked in self._runs.values():
                self._refresh(tracked, now)

    def _tracked(self, run_dir: Path) -> _Tracked:
        tracked = self._runs.get(run_dir)
        if tracked is not None and self.store.get_run(tracked.run_id) is not None:
            return tracked
        project, name = run_dir.parent.name or "izlenen", run_dir.name
        run_id = self.store.find_run(project, name, "watch")
        if run_id is None:
            run_id = self.store.create_run(project, name, source="watch", status="finished")
            tracked = _Tracked(run_id)
        else:
            self.store.clear_metrics(run_id)
            tracked = _Tracked(run_id, reset=True)
        self._runs[run_dir] = tracked
        return tracked

    def _process(self, path: Path, kind: str, tracked: _Tracked) -> None:
        if kind == "csv":
            self._read_csv(path, tracked)
        elif kind == "tb":
            self._read_tb(path, tracked)
        else:
            self._read_results(path, tracked)

    def _add(self, tracked: _Tracked, metrics: list) -> None:
        kept = self.store.add_metrics(tracked.run_id, metrics)
        if kept:
            tracked.max_step = max(tracked.max_step, max(row[1] for row in kept))
            self.store.update_run(tracked.run_id, current_step=tracked.max_step)
            tracked.pending.extend(kept)

    def _read_csv(self, path: Path, tracked: _Tracked) -> None:
        state = tracked.csv.setdefault(path, _CsvState())
        size = path.stat().st_size
        with open(path, "rb") as fh:
            header = fh.readline()
            if not header.endswith(b"\n"):
                return
            if state.header is not None and (header != state.header or size < state.offset):
                # SB3 yeni anahtar görünce dosyayı baştan yazar -> run'ı sıfırla, baştan oku
                self.store.clear_metrics(tracked.run_id)
                tracked.pending.clear()
                tracked.max_step = 0
                tracked.reset = True
                state = tracked.csv[path] = _CsvState()
            if state.header is None:
                state.header, state.offset = header, len(header)
            fh.seek(state.offset)
            chunk = fh.read()
        end = chunk.rfind(b"\n")
        if end < 0:
            return
        chunk = chunk[: end + 1]
        state.offset += len(chunk)
        imported = parse_progress_csv((state.header + chunk).decode("utf-8-sig", errors="replace"))
        self._add(tracked, imported.metrics)

    def _read_tb(self, path: Path, tracked: _Tracked) -> None:
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime)
        if tracked.tb_signature.get(path) == signature:
            return
        tracked.tb_signature[path] = signature
        imported = parse_tfevents(path)
        if imported.errors:
            log.warning("%s: %s", path, "; ".join(imported.errors))
        last = tracked.tb_last_step.setdefault(path, {})
        fresh = [m for m in imported.metrics if m[1] > last.get(m[0], -1)]
        for key, step, *_ in fresh:
            last[key] = max(last.get(key, -1), step)
        self._add(tracked, fresh)

    def _read_results(self, path: Path, tracked: _Tracked) -> None:
        mtime = path.stat().st_mtime
        if tracked.results_mtime == mtime:
            return
        tracked.results_mtime = mtime
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("%s okunamadı: %s", path, exc)
            return
        self.store.update_run(tracked.run_id, results=data if isinstance(data, dict) else {"value": data})
        tracked.results_changed = True

    def _refresh(self, tracked: _Tracked, now: float) -> None:
        active = now - tracked.newest < self.active_window
        fields: dict = {}
        if active:
            fields = {"status": "running", "last_heartbeat": now}
        elif tracked.status in (None, "running"):
            fields = {"status": "finished", "ended_at": now}
        if fields:
            self.store.update_run(tracked.run_id, **fields)
        new_status = fields.get("status", tracked.status)
        if tracked.pending or tracked.reset or tracked.results_changed or new_status != tracked.status:
            self.publish({"type": "batch", "run": self.store.get_run(tracked.run_id),
                          "metrics": tracked.pending, "logs": [], "reset": tracked.reset})
            tracked.pending, tracked.reset, tracked.results_changed = [], False, False
        tracked.status = new_status


class WatchBody(BaseModel):
    path: str = Field(min_length=1)


def watch_router(watcher: FolderWatcher) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/watch")
    def list_roots() -> dict:
        return {"roots": watcher.roots}

    @router.post("/watch")
    def add_root(body: WatchBody) -> dict:
        try:
            added = watcher.add(body.path)
        except NotADirectoryError as exc:
            raise HTTPException(400, detail={"message": str(exc)}) from exc
        threading.Thread(target=watcher.scan_once, daemon=True).start()
        return {"roots": watcher.roots, "added": added}

    @router.delete("/watch")
    def remove_root(path: str) -> dict:
        if not watcher.remove(path):
            raise HTTPException(404, detail={"message": "bu klasör izlenmiyor"})
        return {"roots": watcher.roots}

    return router
