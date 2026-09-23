import math

import pytest

from rlpanel.jsonutil import clean_json
from rlpanel.server.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "panel.db")
    yield s
    s.close()


def test_clean_json_stringifies_non_finite_and_keys():
    assert clean_json({1: [math.nan, math.inf, 2.5, (1, 2)]}) == {"1": ["nan", "inf", 2.5, [1, 2]]}


def test_create_and_get_run(store):
    run_id = store.create_run("P", "r1", seed=0, config={"lr": 0.1}, total_steps=100, host="pc")
    run = store.get_run(run_id)
    assert run["project"] == "P"
    assert run["name"] == "r1"
    assert run["seed"] == 0
    assert run["status"] == "running"
    assert run["source"] == "client"
    assert run["config"] == {"lr": 0.1}
    assert run["results"] is None
    assert run["total_steps"] == 100
    assert run["current_step"] == 0
    assert run["started_at"] > 0 and run["last_heartbeat"] > 0


def test_config_with_nan_is_stored_as_text(store):
    run_id = store.create_run("P", "r", config={"x": math.nan})
    assert store.get_run(run_id)["config"] == {"x": "nan"}


def test_get_run_missing_returns_none(store):
    assert store.get_run(999) is None


def test_list_runs_filters_by_project_newest_first(store):
    a = store.create_run("A", "a1")
    b = store.create_run("B", "b1")
    c = store.create_run("A", "a2")
    assert [r["id"] for r in store.list_runs()] == [c, b, a]
    assert [r["id"] for r in store.list_runs("A")] == [c, a]


def test_update_run_sets_fields_and_rejects_unknown(store):
    run_id = store.create_run("P", "r")
    store.update_run(run_id, status="finished", results={"score": 1}, current_step=7)
    run = store.get_run(run_id)
    assert (run["status"], run["results"], run["current_step"]) == ("finished", {"score": 1}, 7)
    with pytest.raises(ValueError):
        store.update_run(run_id, project_id=3)


def test_add_metrics_drops_non_finite_and_non_numeric(store):
    run_id = store.create_run("P", "r")
    kept = store.add_metrics(run_id, [
        ("a", 1, 1.5, 10.0), ("a", 2, math.nan, 11.0), ("b", 1, math.inf, None),
        ("b", 2, "abc", None), ("b", 3, "2.5", None),
    ])
    assert kept == [["a", 1, 1.5, 10.0], ["b", 3, 2.5, None]]
    assert store.get_metrics(run_id) == {"a": [[1, 1.5, 10.0]], "b": [[3, 2.5, None]]}


def test_get_metrics_filters_keys_and_orders_by_step(store):
    run_id = store.create_run("P", "r")
    store.add_metrics(run_id, [("x", 3, 3.0, None), ("x", 1, 1.0, None), ("y", 1, 9.0, None)])
    assert store.get_metrics(run_id, ["x"]) == {"x": [[1, 1.0, None], [3, 3.0, None]]}
    assert store.metric_keys(run_id) == ["x", "y"]


def test_clear_metrics(store):
    run_id = store.create_run("P", "r")
    store.add_metrics(run_id, [("x", 1, 1.0, None)])
    store.clear_metrics(run_id)
    assert store.get_metrics(run_id) == {}


def test_reward_summary_prefers_known_key_and_downsamples(store):
    run_id = store.create_run("P", "r")
    store.add_metrics(run_id, [("rollout/ep_rew_mean", i, float(i), None) for i in range(200)])
    store.add_metrics(run_id, [("reward", 0, -1.0, None)])
    summary = store.reward_summary(run_id, points=60)
    assert summary["reward_key"] == "rollout/ep_rew_mean"
    assert summary["last_reward"] == 199.0
    assert summary["spark"][0] == 0.0 and summary["spark"][-1] == 199.0
    assert len(summary["spark"]) <= 60
    listed = store.list_runs()[0]
    assert listed["last_reward"] == 199.0


def test_reward_summary_without_reward_metric(store):
    run_id = store.create_run("P", "r")
    assert store.reward_summary(run_id) == {"reward_key": None, "last_reward": None, "spark": []}


def test_logs_after_and_tail(store):
    run_id = store.create_run("P", "r")
    rows = store.add_logs(run_id, [(1.0, "INFO", "a"), (2.0, "ERROR", "b"), (3.0, "INFO", "c")])
    assert [r["line"] for r in rows] == ["a", "b", "c"]
    assert [r["line"] for r in store.get_logs(run_id, after_id=rows[0]["id"])] == ["b", "c"]
    assert [r["line"] for r in store.get_logs(run_id, tail=2)] == ["b", "c"]


def test_mark_unresponsive_only_touches_stale_running(store):
    stale = store.create_run("P", "stale")
    fresh = store.create_run("P", "fresh")
    done = store.create_run("P", "done", status="finished")
    store.update_run(stale, last_heartbeat=100.0)
    store.update_run(done, last_heartbeat=100.0)
    assert store.mark_unresponsive(timeout=30, now=200.0) == [stale]
    assert store.get_run(stale)["status"] == "unresponsive"
    assert store.get_run(fresh)["status"] == "running"
    assert store.get_run(done)["status"] == "finished"


def test_find_run_and_hash(store):
    run_id = store.create_run("P", "r", source="watch", content_hash="abc")
    assert store.find_run("P", "r", "watch") == run_id
    assert store.find_run("P", "r", "client") is None
    assert store.find_run_by_hash("abc") == run_id
    assert store.find_run_by_hash("zzz") is None


def test_delete_run_removes_metrics_and_logs(store):
    run_id = store.create_run("P", "r")
    store.add_metrics(run_id, [("x", 1, 1.0, None)])
    store.add_logs(run_id, [(1.0, "INFO", "a")])
    store.delete_run(run_id)
    assert store.get_run(run_id) is None
    assert store.get_metrics(run_id) == {}
    assert store.get_logs(run_id) == []


def test_data_survives_reopen(tmp_path):
    first = Store(tmp_path / "panel.db")
    run_id = first.create_run("P", "r")
    first.add_metrics(run_id, [("x", 1, 1.0, None)])
    first.close()
    second = Store(tmp_path / "panel.db")
    assert second.get_metrics(run_id) == {"x": [[1, 1.0, None]]}
    second.close()


def test_deleted_run_id_is_never_reused(store):
    first = store.create_run("P", "r")
    store.delete_run(first)
    assert store.create_run("P", "r") != first
