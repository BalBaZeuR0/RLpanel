import io
import zipfile

SB3_CSV = (
    "rollout/ep_rew_mean,time/time_elapsed,time/total_timesteps,train/learning_rate\n"
    "1.0,0,64,0.001\n2.0,1,128,0.001\n"
)


def _upload(client, name, content, project="Deneyler", run="r1"):
    return client.post("/api/upload", data={"project": project, "run": run},
                       files={"file": (name, content, "application/octet-stream")})


def test_upload_progress_csv_creates_finished_run(api_client):
    response = _upload(api_client, "progress.csv", SB3_CSV.encode())
    assert response.status_code == 201
    body = response.json()
    assert body["metrics"] == 6 and body["errors"] == []
    run = api_client.get(f"/api/runs/{body['id']}").json()
    assert (run["project"], run["name"], run["source"], run["status"]) == ("Deneyler", "r1", "upload", "finished")
    assert (run["current_step"], run["total_steps"], run["last_reward"]) == (128, 128, 2.0)


def test_upload_duplicate_returns_409_with_existing_id(api_client):
    first = _upload(api_client, "progress.csv", SB3_CSV.encode()).json()["id"]
    second = _upload(api_client, "progress.csv", SB3_CSV.encode(), run="r2")
    assert second.status_code == 409
    assert second.json()["detail"]["run_id"] == first


def test_upload_defaults_project_and_run_name(api_client):
    body = _upload(api_client, "deney_7.csv", b"step,x\n1,1\n", project="", run="").json()
    run = api_client.get(f"/api/runs/{body['id']}").json()
    assert (run["project"], run["name"]) == ("Yüklenenler", "deney_7")


def test_upload_rejects_empty_unsupported_and_dataless(api_client):
    assert _upload(api_client, "a.csv", b"").status_code == 400
    assert _upload(api_client, "model.pt", b"\x00\x01").status_code == 400
    response = _upload(api_client, "a.csv", b"step,x\n")
    assert response.status_code == 422
    assert "okunabilir veri" in response.json()["detail"]["message"]


def test_upload_results_json_with_nan_is_readable(api_client):
    body = _upload(api_client, "results.json", b'{"score": NaN, "ok": 1}').json()
    run = api_client.get(f"/api/runs/{body['id']}").json()
    assert run["results"] == {"score": "nan", "ok": 1}


def test_export_zip_roundtrips_through_upload(api_client):
    run_id = api_client.post("/api/runs", json={"project": "Proje Ç", "name": "şeed/0", "config": {"lr": 0.1}}).json()["id"]
    api_client.post(f"/api/runs/{run_id}/batch", json={
        "metrics": [["loss", 1, 0.5, 100.0], ["loss", 2, 0.25, 101.0], ["acc", 2, 0.9, None]],
        "logs": [[100.0, "INFO", "başladı"], [101.0, "ERROR", "Traceback\n  satır\nHata"]],
        "results": {"score": 3}, "status": "finished",
    })
    response = api_client.get(f"/api/runs/{run_id}/export.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = response.headers["content-disposition"]
    assert disposition.isascii() and disposition.endswith('.zip"')
    names = set(zipfile.ZipFile(io.BytesIO(response.content)).namelist())
    assert names == {"metrics.csv", "config.json", "results.json", "run.json", "console.log"}

    again = _upload(api_client, "export.zip", response.content, project="Kopya", run="k").json()
    copy = api_client.get(f"/api/runs/{again['id']}").json()
    assert copy["config"] == {"lr": 0.1} and copy["results"] == {"score": 3}
    assert api_client.get(f"/api/runs/{again['id']}/metrics").json() == api_client.get(f"/api/runs/{run_id}/metrics").json()
    logs = api_client.get(f"/api/runs/{again['id']}/logs").json()
    assert [l["line"] for l in logs] == ["başladı", "Traceback\n  satır\nHata"]


def test_export_unknown_run_404(api_client):
    assert api_client.get("/api/runs/999/export.zip").status_code == 404
