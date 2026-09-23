import json
import math
import time

from fastapi.testclient import TestClient

from rlpanel.server.app import create_app


def _create(client, **extra):
    body = {"project": "P", "name": "r", **extra}
    response = client.post("/api/runs", json=body)
    assert response.status_code == 201
    return response.json()["id"]


def test_health(api_client):
    assert api_client.get("/api/health").json()["app"] == "rlpanel"


def test_create_list_get(api_client):
    run_id = _create(api_client, seed=1, host="pc", config={"lr": 0.1}, total_steps=1000)
    listed = api_client.get("/api/runs").json()
    assert [r["id"] for r in listed] == [run_id]
    run = api_client.get(f"/api/runs/{run_id}").json()
    assert run["config"] == {"lr": 0.1} and run["total_steps"] == 1000 and run["metric_keys"] == []
    assert api_client.get("/api/runs?project=nope").json() == []


def test_create_validates_body(api_client):
    assert api_client.post("/api/runs", json={"project": "", "name": "r"}).status_code == 422


def test_batch_stores_metrics_logs_progress(api_client):
    run_id = _create(api_client)
    body = {
        "metrics": [["rollout/ep_rew_mean", 64, 1.5, 10.0], ["train/explained_variance", 64, math.nan, 10.0]],
        "logs": [[10.0, "INFO", "merhaba"]],
        "current_step": 64, "total_steps": 128, "results": {"score": math.nan},
    }
    # rlpanel.http.post_json NaN'ı ham "NaN" olarak yollar; httpx'in json= yolu bunu reddettiği için ham gövde
    response = api_client.post(f"/api/runs/{run_id}/batch", content=json.dumps(body),
                               headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "metrics": 1, "logs": 1}
    run = api_client.get(f"/api/runs/{run_id}").json()
    assert (run["current_step"], run["total_steps"], run["last_reward"]) == (64, 128, 1.5)
    assert run["results"] == {"score": "nan"}
    assert run["metric_keys"] == ["rollout/ep_rew_mean"]
    assert api_client.get(f"/api/runs/{run_id}/metrics").json() == {"rollout/ep_rew_mean": [[64, 1.5, 10.0]]}
    assert api_client.get(f"/api/runs/{run_id}/logs").json()[0]["line"] == "merhaba"


def test_batch_final_status_sets_ended_at(api_client):
    run_id = _create(api_client)
    api_client.post(f"/api/runs/{run_id}/batch", json={"status": "finished"})
    run = api_client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "finished" and run["ended_at"] is not None


def test_batch_unknown_run_404_and_bad_payload_422(api_client):
    assert api_client.post("/api/runs/999/batch", json={}).status_code == 404
    run_id = _create(api_client)
    assert api_client.post(f"/api/runs/{run_id}/batch", json={"metrics": [["x"]]}).status_code == 422
    assert api_client.post(f"/api/runs/{run_id}/batch", json={"status": "weird"}).status_code == 422


def test_metrics_key_filter_and_logs_tail(api_client):
    run_id = _create(api_client)
    api_client.post(f"/api/runs/{run_id}/batch", json={
        "metrics": [["a", 1, 1.0, None], ["b", 1, 2.0, None]],
        "logs": [[1.0, "INFO", "x"], [2.0, "INFO", "y"], [3.0, "INFO", "z"]],
    })
    assert list(api_client.get(f"/api/runs/{run_id}/metrics?keys=b").json()) == ["b"]
    assert [l["line"] for l in api_client.get(f"/api/runs/{run_id}/logs?tail=2").json()] == ["y", "z"]


def test_delete(api_client):
    run_id = _create(api_client)
    assert api_client.delete(f"/api/runs/{run_id}").status_code == 200
    assert api_client.get(f"/api/runs/{run_id}").status_code == 404


def test_websocket_receives_batch_event(api_client):
    run_id = _create(api_client)
    with api_client.websocket_connect("/ws") as ws:
        api_client.post(f"/api/runs/{run_id}/batch", json={"metrics": [["x", 1, 2.0, None]], "logs": []})
        event = ws.receive_json()
    assert event["type"] == "batch"
    assert event["run"]["id"] == run_id
    assert event["metrics"] == [["x", 1, 2.0, None]]


def test_reaper_marks_silent_run_unresponsive_and_batch_revives(tmp_path):
    with TestClient(create_app(tmp_path / "db.sqlite", heartbeat_timeout=0.2)) as client:
        run_id = _create(client)
        time.sleep(0.8)
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "unresponsive"
        client.post(f"/api/runs/{run_id}/batch", json={})
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"


def test_index_is_served(api_client):
    response = api_client.get("/")
    assert response.status_code == 200 and "rlpanel" in response.text


def test_live_server_fixture_answers_health(live_server):
    import urllib.request, json
    with urllib.request.urlopen(live_server.url + "/api/health") as resp:
        assert json.load(resp)["app"] == "rlpanel"
