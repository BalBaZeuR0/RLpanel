import socket
import time

from rlpanel import cli, launcher
from tests.conftest import free_port


def test_health_false_on_closed_port_and_port_free():
    port = free_port()
    assert launcher.health(f"http://127.0.0.1:{port}") is False
    assert launcher.port_free(port) is True


def test_find_server_and_health(live_server):
    assert launcher.health(live_server.url)
    assert launcher.find_server(start=live_server.port, tries=1) == live_server.url
    assert launcher.port_free(live_server.port) is False


def test_ensure_server_joins_running_server(live_server, monkeypatch):
    monkeypatch.setattr(launcher, "spawn_server", lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn")))
    assert launcher.ensure_server(start=live_server.port, tries=1) == (live_server.url, False)


def test_ensure_server_explicit_url(live_server):
    assert launcher.ensure_server(server=live_server.url + "/") == (live_server.url, False)
    dead = f"http://127.0.0.1:{free_port()}"
    assert launcher.ensure_server(server=dead) == (None, False)


def test_ensure_server_env_url(live_server, monkeypatch):
    monkeypatch.setenv("RLPANEL_SERVER", live_server.url)
    assert launcher.ensure_server() == (live_server.url, False)


def test_ensure_server_spawns_and_skips_foreign_busy_port(server_factory, monkeypatch):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    busy = blocker.getsockname()[1]
    spawned = []

    def fake_spawn(port, host="127.0.0.1"):
        spawned.append(port)
        server_factory(port)

    monkeypatch.setattr(launcher, "spawn_server", fake_spawn)
    try:
        url, started = launcher.ensure_server(start=busy, tries=2)
    finally:
        blocker.close()
    assert started is True
    assert spawned == [busy + 1]
    assert url == f"http://127.0.0.1:{busy + 1}"


def test_spawn_server_starts_real_process(tmp_path):
    port = free_port()
    proc = launcher.spawn_server(port)
    try:
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30
        while time.time() < deadline and not launcher.health(url):
            time.sleep(0.2)
        assert launcher.health(url)
        assert (tmp_path / "home" / "panel.db").exists()
    finally:
        proc.terminate()
        proc.wait(10)


def test_cli_serve_when_already_running(live_server, capsys):
    assert cli.main(["serve", "--port", str(live_server.port), "--no-browser"]) == 0
    assert "zaten çalışıyor" in capsys.readouterr().out


def test_cli_import_and_duplicate(live_server, tmp_path, capsys):
    csv_file = tmp_path / "progress.csv"
    csv_file.write_text("step,reward\n1,0.5\n2,0.7\n", encoding="utf-8")
    args = ["import", str(csv_file), "--server", live_server.url, "--project", "Cli", "--run", "r1"]
    assert cli.main(args) == 0
    run = live_server.store.list_runs("Cli")[0]
    assert run["name"] == "r1" and run["source"] == "upload"
    assert cli.main(args) == 1
    assert "zaten yüklenmiş" in capsys.readouterr().err


def test_cli_watch(live_server, tmp_path):
    folder = tmp_path / "izle"
    folder.mkdir()
    assert cli.main(["watch", str(folder), "--server", live_server.url]) == 0
    assert str(folder.resolve()) in live_server.app.state.watcher.roots
