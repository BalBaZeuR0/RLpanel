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


import io
import zipfile


def test_run_page_strip_charts_and_downloads(page, live_server):
    metrics = reward_points(n=5) + [
        ["train/learning_rate", 400, 0.0003, 1004.0], ["rollout/ep_len_mean", 400, 42, 1004.0],
        ["rollout/success_rate", 400, 0.75, 1004.0], ["time/fps", 400, 100, 1004.0], ["visible_rate", 400, 0.9, 1004.0],
    ]
    run_id = make_run(live_server.url, metrics=metrics, total_steps=1000, current_step=400,
                      config={"lr": 0.0003, "net": {"arch": [64, 64]}})
    page.goto(page.base_url + f"/#/run/{run_id}")
    page.locator(".chart-card").first.wait_for()
    tiles = page.locator(".strip").text_content()  # text_content: CSS büyük harf dönüşümünden (tr: i→İ) etkilenmez
    for label in ("İlerleme", "Anlık reward", "En iyi reward", "Episode uzunluğu", "Başarı oranı", "Learning rate", "Geçen süre"):
        assert label in tiles
    assert "%75" in tiles and "%40" in tiles
    assert page.locator(".chart-group h3").first.text_content().startswith("Temel")
    assert page.locator('.chart-card[data-key="visible_rate"]').count() == 1

    card = page.locator('.chart-card[data-key="rollout/ep_rew_mean"]')
    with page.expect_download() as info:
        card.get_by_role("button", name="rollout/ep_rew_mean CSV indir").click()
    text = open(info.value.path(), encoding="utf-8").read()
    assert text.startswith("adim,") and "400" in text
    with page.expect_download() as info:
        card.get_by_role("button", name="rollout/ep_rew_mean PNG indir").click()
    assert open(info.value.path(), "rb").read(4) == b"\x89PNG"

    page.get_by_role("tab", name="Config").click()
    assert "net.arch" in page.locator(".kv").inner_text()


def test_run_page_live_update_and_console(page, live_server):
    run_id = make_run(live_server.url, metrics=reward_points(n=2), logs=[[1000.0, "INFO", "ilk satır"]], total_steps=1000)
    page.goto(page.base_url + f"/#/run/{run_id}")
    page.locator(".chart-card").first.wait_for()
    page.wait_for_function("document.querySelector('#conn').dataset.state === 'open'")
    httpx.post(f"{live_server.url}/api/runs/{run_id}/batch", json={
        "metrics": [["rollout/ep_rew_mean", 300, 77.0, 1003.0], ["yeni/metrik", 300, 1.0, 1003.0]],
        "logs": [[1003.0, "ERROR", "canlı hata"]], "current_step": 300})
    page.wait_for_function("document.querySelector('.strip').textContent.includes('77')")
    page.locator('.chart-card[data-key="yeni/metrik"]').wait_for()
    page.get_by_role("tab", name="Konsol").click()
    page.locator(".console .log-line", has_text="canlı hata").wait_for()
    assert page.locator(".console .log-line", has_text="ilk satır").count() == 1


def test_run_page_compares_with_previous_runs(page, live_server):
    old = make_run(live_server.url, name="seed0", metrics=reward_points(scale=1.0, n=5), status="finished")
    live = make_run(live_server.url, name="seed1", metrics=reward_points(scale=2.0, n=3), total_steps=1000)
    page.goto(page.base_url + f"/#/run/{live}?ref={old}")
    page.locator(".compare-bar .chip", has_text="seed0").wait_for()
    strip = page.locator(".strip").text_content()
    assert "aynı adımda" in strip and "+2" in strip
    page.get_by_role("button", name="seed0 referansını kaldır").click()
    assert f"ref={old}" not in page.url
    page.get_by_role("button", name="Son run").click()
    page.locator(".compare-bar .chip", has_text="seed0").wait_for()
    assert f"ref={old}" in page.url


def test_run_page_zip_contains_data_and_pngs(page, live_server):
    run_id = make_run(live_server.url, metrics=reward_points(), logs=[[1000.0, "INFO", "x"]], total_steps=1000)
    page.goto(page.base_url + f"/#/run/{run_id}")
    page.locator(".chart-card").first.wait_for()
    with page.expect_download() as info:
        page.get_by_role("button", name="Tümünü indir (zip)").click()
    names = zipfile.ZipFile(io.BytesIO(open(info.value.path(), "rb").read())).namelist()
    assert "metrics.csv" in names and "console.log" in names
    assert "grafikler/rollout_ep_rew_mean.png" in names


def test_missing_run_shows_message(page, live_server):
    page.goto(page.base_url + "/#/run/99999")
    page.get_by_text("Run bulunamadı").wait_for()
