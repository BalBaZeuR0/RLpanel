import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def page(live_server):
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 900})
        pg = context.new_page()
        pg.set_default_timeout(10_000)
        pg.base_url = live_server.url
        yield pg
        browser.close()
