import os
import time

import pytest

from rlpanel.server.store import Store
from rlpanel.server.watcher import FolderWatcher

HEADER = "rollout/ep_rew_mean,time/total_timesteps\n"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    yield s
    s.close()


@pytest.fixture
def events():
    return []


def _watcher(store, events, tmp_path, **kw):
    return FolderWatcher(store, events.append, state_file=tmp_path / "watch.json", **kw)


def _run_dir(tmp_path):
    run_dir = tmp_path / "runs" / "Proje" / "seed_0"
    run_dir.mkdir(parents=True)
    return run_dir


def test_incremental_csv_creates_run_and_appends_without_duplicates(store, events, tmp_path):
    run_dir = _run_dir(tmp_path)
    csv_path = run_dir / "progress.csv"
    csv_path.write_text(HEADER + "1.0,64\n2.0,128\n", encoding="utf-8")
    watcher = _watcher(store, events, tmp_path)
    watcher.add(tmp_path / "runs")
    watcher.scan_once()
    run_id = store.find_run("Proje", "seed_0", "watch")
    assert run_id is not None
    assert [p[0] for p in store.get_metrics(run_id)["rollout/ep_rew_mean"]] == [64, 128]
    with open(csv_path, "a", encoding="utf-8") as fh:
        fh.write("3.0,192\n4.0,2")  # son satır yarım
    watcher.scan_once()
    assert [p[0] for p in store.get_metrics(run_id)["rollout/ep_rew_mean"]] == [64, 128, 192]
    with open(csv_path, "a", encoding="utf-8") as fh:
        fh.write("56\n")
    watcher.scan_once()
    assert [p[0] for p in store.get_metrics(run_id)["rollout/ep_rew_mean"]] == [64, 128, 192, 256]
    assert store.get_run(run_id)["current_step"] == 256
    batches = [e for e in events if e["type"] == "batch"]
    assert sum(len(e["metrics"]) for e in batches) == 4


def test_rewritten_csv_resets_metrics(store, events, tmp_path):
    run_dir = _run_dir(tmp_path)
    csv_path = run_dir / "progress.csv"
    csv_path.write_text(HEADER + "1.0,64\n2.0,128\n", encoding="utf-8")
    watcher = _watcher(store, events, tmp_path)
    watcher.add(tmp_path / "runs")
    watcher.scan_once()
    csv_path.write_text("rollout/ep_rew_mean,time/total_timesteps,train/loss\n1.0,64,\n2.0,128,0.5\n",
                        encoding="utf-8")
    watcher.scan_once()
    run_id = store.find_run("Proje", "seed_0", "watch")
    metrics = store.get_metrics(run_id)
    assert [p[0] for p in metrics["rollout/ep_rew_mean"]] == [64, 128]
    assert metrics["train/loss"] == [[128, 0.5, None]]
    assert any(e.get("reset") for e in events if e["type"] == "batch")


def test_results_json_is_attached(store, events, tmp_path):
    run_dir = _run_dir(tmp_path)
    (run_dir / "progress.csv").write_text(HEADER + "1.0,64\n", encoding="utf-8")
    (run_dir / "results.json").write_text('{"score": 5}', encoding="utf-8")
    watcher = _watcher(store, events, tmp_path)
    watcher.add(tmp_path / "runs")
    watcher.scan_once()
    assert store.get_run(store.find_run("Proje", "seed_0", "watch"))["results"] == {"score": 5}


def test_status_follows_file_activity(store, events, tmp_path):
    run_dir = _run_dir(tmp_path)
    csv_path = run_dir / "progress.csv"
    csv_path.write_text(HEADER + "1.0,64\n", encoding="utf-8")
    mtime = csv_path.stat().st_mtime
    watcher = _watcher(store, events, tmp_path, active_window=60)
    watcher.add(tmp_path / "runs")
    watcher.scan_once(now=mtime + 1)
    run_id = store.find_run("Proje", "seed_0", "watch")
    assert store.get_run(run_id)["status"] == "running"
    watcher.scan_once(now=mtime + 120)
    assert store.get_run(run_id)["status"] == "finished"


def test_restart_reuses_run_without_duplicating(store, events, tmp_path):
    run_dir = _run_dir(tmp_path)
    (run_dir / "progress.csv").write_text(HEADER + "1.0,64\n2.0,128\n", encoding="utf-8")
    first = _watcher(store, events, tmp_path)
    first.add(tmp_path / "runs")
    first.scan_once()
    second = _watcher(store, events, tmp_path)  # roots state file'dan yüklenir
    assert second.roots == [str((tmp_path / "runs").resolve())]
    second.scan_once()
    run_id = store.find_run("Proje", "seed_0", "watch")
    assert len(store.get_metrics(run_id)["rollout/ep_rew_mean"]) == 2
    assert len([r for r in store.list_runs() if r["source"] == "watch"]) == 1


def test_tfevents_ignored_when_progress_csv_exists(store, events, tmp_path):
    run_dir = _run_dir(tmp_path)
    (run_dir / "progress.csv").write_text(HEADER + "1.0,64\n", encoding="utf-8")
    (run_dir / "events.out.tfevents.123.pc").write_bytes(b"not really tfevents")
    watcher = _watcher(store, events, tmp_path)
    watcher.add(tmp_path / "runs")
    watcher.scan_once()
    run_id = store.find_run("Proje", "seed_0", "watch")
    assert list(store.get_metrics(run_id)) == ["rollout/ep_rew_mean"]


def test_add_rejects_missing_folder_and_remove(store, events, tmp_path):
    watcher = _watcher(store, events, tmp_path)
    with pytest.raises(NotADirectoryError):
        watcher.add(tmp_path / "yok")
    root = tmp_path / "runs"
    root.mkdir()
    watcher.add(root)
    assert watcher.remove(root) is True
    assert watcher.roots == []
    assert watcher.remove(root) is False


def test_watch_api(api_client, tmp_path):
    folder = tmp_path / "izle"
    folder.mkdir()
    response = api_client.post("/api/watch", json={"path": str(folder)})
    assert response.status_code == 200
    assert str(folder.resolve()) in response.json()["roots"]
    assert api_client.get("/api/watch").json()["roots"] == [str(folder.resolve())]
    assert api_client.post("/api/watch", json={"path": str(tmp_path / "yok")}).status_code == 400
    assert api_client.delete("/api/watch", params={"path": str(folder)}).json()["roots"] == []
    assert api_client.delete("/api/watch", params={"path": str(folder)}).status_code == 404


def test_background_thread_picks_up_files(live_server, tmp_path):
    run_dir = _run_dir(tmp_path)
    (run_dir / "progress.csv").write_text(HEADER + "1.0,64\n", encoding="utf-8")
    watcher = live_server.app.state.watcher
    watcher.interval = 0.1
    watcher.add(tmp_path / "runs")
    deadline = time.time() + 10
    while time.time() < deadline and live_server.store.find_run("Proje", "seed_0", "watch") is None:
        time.sleep(0.1)
    assert live_server.store.find_run("Proje", "seed_0", "watch") is not None
