import logging
import math
import sys

import pytest

from rlpanel import Panel
from rlpanel.server.importers import parse_buffer_jsonl
from tests.conftest import free_port


def _panel(url, tmp_path, **kw):
    kw.setdefault("capture_logs", False)
    kw.setdefault("flush_interval", 60)  # testlerde gönderimi elle tetikliyoruz
    return Panel("Test", "r1", server=url, run_dir=tmp_path / "run", open_browser=False, **kw)


def test_panel_creates_run_and_sends_metrics_logs_progress(live_server, tmp_path):
    panel = _panel(live_server.url, tmp_path, config={"lr": 0.1, "bad": math.nan}, seed=3, total_steps=100)
    assert panel.run_id is not None
    assert panel.url == f"{live_server.url}/#/run/{panel.run_id}"
    panel.log({"reward": 1.5, "nan": math.nan, "text": "x", "np": 2}, step=10)
    panel.log_text("merhaba", "WARNING")
    panel.progress(10)
    panel.result({"score": 1})
    panel.result({"extra": 2})
    panel._flush_safe(force=True)
    store = live_server.store
    run = store.get_run(panel.run_id)
    assert run["config"] == {"lr": 0.1, "bad": "nan"}
    assert (run["seed"], run["total_steps"], run["current_step"]) == (3, 100, 10)
    assert run["results"] == {"score": 1, "extra": 2}
    assert {k: [p[:2] for p in v] for k, v in store.get_metrics(panel.run_id).items()} == {
        "reward": [[10, 1.5]], "np": [[10, 2.0]]}
    assert store.get_logs(panel.run_id)[0]["line"] == "merhaba"
    panel.finish()
    run = store.get_run(panel.run_id)
    assert run["status"] == "finished" and run["ended_at"] is not None
    panel.finish("crashed")  # ikinci çağrı etkisiz
    assert store.get_run(panel.run_id)["status"] == "finished"


def test_offline_panel_buffers_to_jsonl(tmp_path):
    dead = f"http://127.0.0.1:{free_port()}"
    panel = _panel(dead, tmp_path, config={"lr": 1})
    assert panel.run_id is None
    panel.log({"loss": 0.5}, step=1)
    panel.finish()
    imported = parse_buffer_jsonl(panel.buffer_path.read_text(encoding="utf-8"))
    assert imported.config == {"lr": 1}
    assert [m[:3] for m in imported.metrics] == [["loss", 1, 0.5]]
    assert imported.status == "finished"


def test_buffer_is_replayed_when_server_comes_back(server_factory, tmp_path):
    port = free_port()
    panel = _panel(f"http://127.0.0.1:{port}", tmp_path)
    panel.log({"loss": 0.5}, step=1)
    panel._flush_safe(force=True)
    assert panel.buffer_path.exists()
    handle = server_factory(port)
    panel.log({"loss": 0.4}, step=2)
    panel._flush_safe(force=True)
    assert panel.run_id is not None
    assert [p[0] for p in handle.store.get_metrics(panel.run_id)["loss"]] == [1, 2]
    assert not panel.buffer_path.exists()
    panel.finish()


def test_run_deleted_on_server_is_recreated(live_server, tmp_path):
    panel = _panel(live_server.url, tmp_path)
    old_id = panel.run_id
    live_server.store.delete_run(old_id)
    panel.log({"loss": 0.5}, step=1)
    panel._flush_safe(force=True)   # 404 -> çevrimdışı + yedek
    panel._flush_safe(force=True)   # yeniden bağlan -> yeni run + yedeği gönder
    assert panel.run_id is not None and panel.run_id != old_id
    assert live_server.store.get_metrics(panel.run_id)["loss"][0][:2] == [1, 0.5]
    panel.finish()


def test_context_manager_marks_crash_with_traceback(live_server, tmp_path):
    with pytest.raises(ValueError):
        with _panel(live_server.url, tmp_path) as panel:
            raise ValueError("patladı")
    assert live_server.store.get_run(panel.run_id)["status"] == "crashed"
    assert "ValueError: patladı" in live_server.store.get_logs(panel.run_id)[-1]["line"]


def test_keyboard_interrupt_marks_stopped(live_server, tmp_path):
    with pytest.raises(KeyboardInterrupt):
        with _panel(live_server.url, tmp_path) as panel:
            raise KeyboardInterrupt
    assert live_server.store.get_run(panel.run_id)["status"] == "stopped"


def test_excepthook_marks_crash(live_server, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: seen.append(a[0]))
    panel = _panel(live_server.url, tmp_path)
    try:
        raise RuntimeError("yakalanmadı")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    assert live_server.store.get_run(panel.run_id)["status"] == "crashed"
    assert seen == [RuntimeError]


def test_disabled_panel_is_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("RLPANEL_DISABLE", "1")
    panel = _panel("http://127.0.0.1:1", tmp_path)
    panel.log({"x": 1}, step=1)
    panel.finish()
    assert panel.disabled and panel.run_id is None and panel.url is None
    assert not panel.buffer_path.exists()


def test_captured_logs_reach_console(live_server, tmp_path):
    panel = _panel(live_server.url, tmp_path, capture_logs=True)
    print("çıktı satırı")
    logging.getLogger("egitim").error("hata satırı")
    panel.finish()
    lines = [(l["line"], l["level"]) for l in live_server.store.get_logs(panel.run_id)]
    assert ("çıktı satırı", "INFO") in lines
    assert ("hata satırı", "ERROR") in lines
