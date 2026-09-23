"""Son incelemede bulunan hataları sabitleyen testler."""
import json
import logging
import subprocess
import sys
import time

from rlpanel import Panel, launcher, logcapture
from tests.conftest import free_port


def _panel(url, tmp_path, **kw):
    kw.setdefault("capture_logs", False)
    kw.setdefault("flush_interval", 60)
    return Panel("Test", "seed0", server=url, run_dir=tmp_path / "run", open_browser=False, **kw)


def test_leftover_buffer_is_set_aside_not_replayed_into_new_run(live_server, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    old = run_dir / ".rlpanel_buffer.jsonl"
    lines = [{"op": "create", "project": "Test", "name": "seed0"},
             {"op": "batch", "batch": {"metrics": [["reward", 999, 1.0, None]], "logs": [], "status": "finished"}}]
    old.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    panel = _panel(live_server.url, tmp_path)
    panel.log({"reward": 5.0}, step=1)
    panel._flush_safe(force=True)
    run = live_server.store.get_run(panel.run_id)
    assert run["status"] == "running"
    assert [p[0] for p in live_server.store.get_metrics(panel.run_id)["reward"]] == [1]
    kept = list(run_dir.glob(".rlpanel_buffer.*.jsonl"))
    assert len(kept) == 1 and "999" in kept[0].read_text(encoding="utf-8")
    panel.finish()


def test_stale_run_id_from_replaced_db_is_not_reused(server_factory, tmp_path):
    port = free_port()
    first = server_factory(port, db="first.db")
    panel = _panel(first.url, tmp_path)
    assert panel.run_id == 1
    first.server.should_exit = True
    first.thread.join(10)
    second = server_factory(port, db="second.db")
    other = second.store.create_run("Baska", "egitim")  # yeni veritabanında id 1 başka bir run'ın
    assert other == 1
    panel.log({"loss": 0.5}, step=1)
    panel._flush_safe(force=True)
    panel._flush_safe(force=True)
    assert second.store.get_metrics(other) == {}
    assert panel.run_id != other
    assert second.store.get_metrics(panel.run_id)["loss"][0][:2] == [1, 0.5]
    panel.finish()


def test_log_capture_adds_no_root_handler_so_terminal_logging_keeps_working():
    root = logging.getLogger()
    before = list(root.handlers)
    factory = logging.getLogRecordFactory()
    lines = []
    sink = lambda line, level: lines.append((line, level))
    logcapture.set_sink(sink)
    try:
        assert root.handlers == before  # basicConfig ve lastResort bozulmasın
        logging.getLogger("kullanici").warning("uyari")
    finally:
        logcapture.clear_sink(sink)
    assert ("uyari", "WARNING") in lines
    assert logging.getLogRecordFactory() is factory


def test_finish_offline_tries_to_reconnect_only_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(launcher, "health", lambda url, timeout=0.5: calls.append(url) or False)
    panel = _panel(f"http://127.0.0.1:{free_port()}", tmp_path)
    calls.clear()
    for step in range(30_000):
        panel.log({"x": 1.0}, step=step)
    started = time.monotonic()
    panel.finish()
    assert len(calls) <= 1
    assert time.monotonic() - started < 10
    assert panel.buffer_path.exists()


def test_ensure_server_stops_waiting_when_spawned_process_dies(monkeypatch):
    monkeypatch.setattr(launcher, "spawn_server",
                        lambda port, host="127.0.0.1": subprocess.Popen([sys.executable, "-c", "pass"]))
    started = time.monotonic()
    assert launcher.ensure_server(start=free_port(), tries=1, wait=20) == (None, False)
    assert time.monotonic() - started < 5


def test_bad_step_never_raises_into_training(live_server, tmp_path):
    panel = _panel(live_server.url, tmp_path)
    panel.log({"x": 1.0}, step=None)
    panel.log({"x": 1.0}, step="abc")
    panel.finish()
