import urllib.request

import pytest

pytestmark = pytest.mark.e2e


def test_static_assets_have_browser_friendly_types(live_server):
    for path, expected in [("/js/core.js", "javascript"), ("/styles.css", "text/css"),
                           ("/vendor/uPlot.iife.min.js", "javascript")]:
        with urllib.request.urlopen(live_server.url + path) as resp:
            assert expected in resp.headers["content-type"], path


def test_core_helpers(page):
    page.goto(page.base_url + "/")
    result = page.evaluate("""async () => {
      const c = await import('/js/core.js');
      return {
        ema0: c.ema([1, 2, 3], 0),
        ema: c.ema([10, 10, null, 10], 0.9).map(v => v === null ? null : Math.round(v * 1000) / 1000),
        interpMid: c.interpAt([0, 10], [0, 100], 5),
        interpOut: c.interpAt([0, 10], [0, 100], 11),
        align: c.alignSeries([{xs: [1, 3], ys: [10, 30]}, {xs: [2, 3], ys: [20, 31]}]),
        groups: c.groupMetricKeys(['train/loss', 'rollout/ep_rew_mean', 'visible_rate', 'train/learning_rate', 'eval/x']),
        delta: c.deltaAtStep({xs: [0, 100], ys: [0, 12]}, {xs: [0, 200], ys: [0, 20]}),
        deltaNone: c.deltaAtStep({xs: [0, 300], ys: [0, 1]}, {xs: [0, 200], ys: [0, 20]}),
        band: c.meanStd([{xs: [0, 10], ys: [0, 10]}, {xs: [0, 10], ys: [2, 12]}], 3),
        groupKeys: ['exp/seed_0', 'run_3', 'ppo', 'a-seed-12'].map(c.groupKey),
        compact: [950, 1500, 630000, 1250000].map(c.formatCompact),
        dur: [5, 125, 7300].map(c.formatDuration),
        prog: c.progressInfo({total_steps: 1000, current_step: 250, started_at: 100, status: 'running'}, 50, 150),
        flat: c.flatten({a: {b: 1, c: [1, 2]}, d: null}),
        csv: c.toCSV(['x', 'y'], [[1, 'a,b'], [2, null]]),
        ticks: c.niceTicks(0, 97).ticks,
        svg: c.chartSVG({title: 'reward', series: [{label: 'r', color: '#000', xs: [0, 1], ys: [1, 2]}]}),
        svgEmpty: c.chartSVG({title: 'boş', series: []}),
        pick: c.pickKey(['a', 'rollout/ep_rew_mean'], c.CORE_KEYS.reward),
      };
    }""")
    assert result["ema0"] == [1, 2, 3]
    assert result["ema"] == [10, 10, None, 10]
    assert result["interpMid"] == 50 and result["interpOut"] is None
    assert result["align"] == [[1, 2, 3], [10, None, 30], [None, 20, 31]]
    assert result["groups"] == [
        {"title": "Temel", "keys": ["rollout/ep_rew_mean", "train/learning_rate"]},
        {"title": "eval", "keys": ["eval/x"]},
        {"title": "train", "keys": ["train/loss"]},
        {"title": "Özel", "keys": ["visible_rate"]},
    ]
    assert result["delta"]["ref"] == 10 and result["delta"]["diff"] == 2 and round(result["delta"]["pct"]) == 20
    assert result["deltaNone"] is None
    assert result["band"]["mean"] == [1, 6, 11] and result["band"]["lo"] == [0, 5, 10]
    assert result["groupKeys"] == ["exp", "run", "ppo", "a"]
    assert result["compact"] == ["950", "1.5k", "630k", "1.25M"]
    assert result["dur"] == ["5sn", "2dk 5sn", "2sa 1dk"]
    assert result["prog"]["pct"] == 25 and result["prog"]["eta"] == 15 and result["prog"]["elapsed"] == 50
    assert result["flat"] == [["a.b", "1"], ["a.c", "[1,2]"], ["d", "null"]]
    assert result["csv"] == 'x,y\n1,"a,b"\n2,\n'
    assert result["ticks"] == [0, 20, 40, 60, 80, 100]
    assert result["svg"].startswith("<svg") and "<path" in result["svg"] and "reward" in result["svg"]
    assert "veri yok" in result["svgEmpty"]
    assert result["pick"] == "rollout/ep_rew_mean"


def test_shell_renders_and_theme_toggles(page):
    page.goto(page.base_url + "/")
    assert page.locator("#conn").get_attribute("data-state") in ("open", "connecting")
    page.wait_for_function("document.querySelector('#conn').dataset.state === 'open'")
    theme = page.evaluate("document.documentElement.dataset.theme")
    page.click("#theme-toggle")
    assert page.evaluate("document.documentElement.dataset.theme") != theme


def test_chart_model_csv_svg_png(page):
    page.goto(page.base_url + "/")
    result = page.evaluate("""async () => {
      const ch = await import('/js/charts.js');
      const lines = [
        {label: 'bu run', color: ch.LIVE_COLOR, points: [[0, 1, 100], [10, 3, 101], [20, 5, 103]]},
        {label: 'ref', color: ch.PALETTE[0], points: [[0, 2, 50], [20, 4, 52]]},
      ];
      const model = ch.buildModel(lines, {smoothing: 0.5, xmode: 'step', log: false});
      const timeModel = ch.buildModel(lines, {smoothing: 0, xmode: 'time', log: true});
      const band = ch.buildModel([lines[0]], {smoothing: 0, xmode: 'step', band: {label: 'ref', color: '#94A3B8',
        sources: [[[0, 0, null], [20, 10, null]], [[0, 2, null], [20, 12, null]]]}});
      const png = await ch.svgToPng(ch.modelSVG(model, 'reward'));
      const head = new Uint8Array(await png.slice(0, 4).arrayBuffer());
      return {
        csv: ch.modelCSV(model).split('\\n')[0],
        rawKept: model.lines[0].rawYs, smoothed: model.lines[0].ys[0],
        timeXs: timeModel.lines[0].xs, log: timeModel.log,
        bandMean: band.band.mean.slice(0, 1),
        svg: ch.modelSVG(band, 'x').includes('fill-opacity="0.18"'),
        pngHead: Array.from(head),
      };
    }""")
    assert result["csv"] == "adim,bu run,bu run (ham),ref,ref (ham)"
    assert result["rawKept"] == [1, 3, 5] and result["smoothed"] == 1
    assert result["timeXs"] == [0, 1, 3] and result["log"] is True
    assert result["bandMean"] == [1]
    assert result["svg"] is True
    assert result["pngHead"] == [0x89, 0x50, 0x4E, 0x47]
