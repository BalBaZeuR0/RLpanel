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
