import socket

import pytest


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RLPANEL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("RLPANEL_NO_BROWSER", "1")
    for name in ("RLPANEL_SERVER", "RLPANEL_DISABLE", "RLPANEL_DB"):
        monkeypatch.delenv(name, raising=False)


import threading
import time
from types import SimpleNamespace

import uvicorn
from fastapi.testclient import TestClient


@pytest.fixture
def server_factory(tmp_path):
    from rlpanel.server.app import create_app

    handles = []

    def start(port: int | None = None, heartbeat_timeout: float = 30.0, db: str = "panel.db"):
        port = port or free_port()
        app = create_app(tmp_path / db, heartbeat_timeout=heartbeat_timeout)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.time() + 15
        while not server.started:
            if time.time() > deadline or not thread.is_alive():
                raise RuntimeError("test sunucusu başlamadı")
            time.sleep(0.02)
        handle = SimpleNamespace(url=f"http://127.0.0.1:{port}", port=port, app=app,
                                 store=app.state.store, server=server, thread=thread)
        handles.append(handle)
        return handle

    yield start
    for handle in handles:
        handle.server.should_exit = True
        handle.thread.join(10)


@pytest.fixture
def live_server(server_factory):
    return server_factory()


@pytest.fixture
def api_client(tmp_path):
    from rlpanel.server.app import create_app

    with TestClient(create_app(tmp_path / "panel.db")) as client:
        yield client
