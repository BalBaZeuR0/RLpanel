"""Sunucu keşfi ve başlatma: eğitim başlarken panel yoksa arka planda açılır."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser

from rlpanel import http, paths

DEFAULT_PORT = 8765
PORT_TRIES = 10


def health(url: str, timeout: float = 0.5) -> bool:
    try:
        return http.get_json(url.rstrip("/") + "/api/health", timeout=timeout).get("app") == "rlpanel"
    except Exception:
        return False


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_server(start: int = DEFAULT_PORT, tries: int = PORT_TRIES) -> str | None:
    for port in range(start, start + tries):
        url = f"http://127.0.0.1:{port}"
        if not port_free(port) and health(url):
            return url
    return None


def spawn_server(port: int, host: str = "127.0.0.1") -> subprocess.Popen:
    home = paths.home_dir()
    home.mkdir(parents=True, exist_ok=True)
    log_file = open(home / "server.log", "ab")
    command = [sys.executable, "-m", "rlpanel", "serve", "--port", str(port), "--host", host, "--no-browser"]
    kwargs: dict = {"stdout": log_file, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def ensure_server(server: str | None = None, start: int = DEFAULT_PORT, tries: int = PORT_TRIES,
                  wait: float = 20.0) -> tuple[str | None, bool]:
    """Çalışan sunucunun adresini döndürür; yoksa başlatır. (adres, şimdi_başlatıldı)"""
    server = server or os.environ.get("RLPANEL_SERVER")
    if server:
        server = server.rstrip("/")
        return (server, False) if health(server) else (None, False)
    found = find_server(start, tries)
    if found:
        return found, False
    for port in range(start, start + tries):
        if not port_free(port):
            continue
        process = spawn_server(port)
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + wait
        while time.time() < deadline:
            if health(url):
                return url, True
            if process.poll() is not None:
                # süreç öldü: çoğunlukla aynı anda başlayan başka bir eğitim portu kaptığı için
                return (url, False) if health(url) else (None, False)
            time.sleep(0.2)
        return None, False
    return None, False


def open_browser(url: str | None) -> None:
    if not url or os.environ.get("RLPANEL_NO_BROWSER") == "1":
        return
    try:
        webbrowser.open(url)
    except Exception:
        pass
