import httpx
import pytest

pytestmark = pytest.mark.e2e


def make_run(url, name="seed0", project="Proje", metrics=(), logs=(), status=None, current_step=None, **extra):
    run_id = httpx.post(f"{url}/api/runs", json={"project": project, "name": name, **extra}).json()["id"]
    body = {"metrics": list(metrics), "logs": list(logs)}
    if status:
        body["status"] = status
    if current_step is not None:
        body["current_step"] = current_step
    httpx.post(f"{url}/api/runs/{run_id}/batch", json=body)
    return run_id


def reward_points(scale=1.0, n=5):
    return [["rollout/ep_rew_mean", i * 100, scale * i, 1000.0 + i] for i in range(n)]


def test_home_shows_cards_and_updates_live(page, live_server):
    run_id = make_run(live_server.url, metrics=reward_points(), total_steps=1000)
    page.goto(page.base_url + "/#/")
    card = page.locator(f'.run-card[data-id="{run_id}"]')
    card.wait_for()
    assert card.locator(".metric-big .value").inner_text() == "4"
    page.wait_for_function("document.querySelector('#conn').dataset.state === 'open'")
    httpx.post(f"{live_server.url}/api/runs/{run_id}/batch",
               json={"metrics": [["rollout/ep_rew_mean", 500, 12.5, 1005.0]], "logs": [], "current_step": 500})
    page.wait_for_function(f"document.querySelector('.run-card[data-id=\"{run_id}\"] .metric-big .value').textContent === '12,5'")
    assert "%50" in card.locator(".progress-text").inner_text()


def test_home_new_run_appears_without_reload(page, live_server):
    page.goto(page.base_url + "/#/")
    page.wait_for_function("document.querySelector('#conn').dataset.state === 'open'")
    run_id = make_run(live_server.url, name="yeni")
    page.locator(f'.run-card[data-id="{run_id}"]').wait_for()


def test_upload_flow_opens_run_page(page, live_server, tmp_path):
    csv_file = tmp_path / "progress.csv"
    csv_file.write_text("rollout/ep_rew_mean,time/total_timesteps\n1.0,64\n2.0,128\n", encoding="utf-8")
    page.goto(page.base_url + "/#/")
    page.get_by_role("button", name="Log yükle").click()
    page.set_input_files("#up-file", str(csv_file))
    page.fill("#up-project", "Yükleme Testi")
    page.fill("#up-run", "eski-egitim")
    page.get_by_role("button", name="Yükle", exact=True).click()
    page.wait_for_url("**/#/run/*")


def test_compare_selection_navigates(page, live_server):
    a = make_run(live_server.url, name="a", metrics=reward_points())
    b = make_run(live_server.url, name="b", metrics=reward_points(2))
    page.goto(page.base_url + "/#/")
    page.locator(f'.run-card[data-id="{a}"] input[type=checkbox]').check()
    page.locator(f'.run-card[data-id="{b}"] input[type=checkbox]').check()
    page.get_by_role("button", name="Karşılaştır").click()
    page.wait_for_url(f"**/#/compare?ids=*")
