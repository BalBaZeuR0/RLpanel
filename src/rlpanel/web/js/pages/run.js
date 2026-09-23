import { api } from "../api.js";
import { MetricBoard } from "../board.js";
import { LIVE_COLOR, PALETTE } from "../charts.js";
import { CORE_KEYS, deltaAtStep, flatten, formatCompact, formatDuration, formatNum, groupKey, pickKey, progressInfo, safeName, toXY } from "../core.js";
import { onEvent } from "../live.js";
import { SOURCE, STATUS, confirmDelete, download, fmtDate, h, icon, statusBadge, toast } from "../ui.js";

const TABS = [["charts", "Grafikler"], ["console", "Konsol"], ["config", "Config"], ["results", "Sonuçlar"]];
const LEVELS = ["", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "STDERR"];
const MAX_CONSOLE_ROWS = 3000;

export async function renderRun(view, id, params) {
  view.replaceChildren(h("div", { class: "loading" }, "Yükleniyor…"));
  let run, points, allRuns, logs;
  try {
    [run, points, allRuns, logs] = await Promise.all([api.run(id), api.metrics(id), api.runs(), api.logs(id, { tail: 5000 })]);
  } catch (e) {
    view.replaceChildren(h("div", { class: "empty" }, h("h2", {}, "Run bulunamadı"),
      h("p", {}, e.status === 404 ? "Silinmiş olabilir ya da başka bir panel veritabanına ait." : e.message),
      h("a", { class: "btn", href: "#/" }, icon("arrow-left"), "Eğitimlere dön")));
    return () => {};
  }

  const state = { run, points, refs: [], band: false, logs, tab: "charts", level: "", query: "", autoscroll: true };
  const others = () => allRuns.filter((r) => r.id !== run.id);
  const board = new MetricBoard({ keysFrom: "primary", bandRole: "ref", fileBase: `${run.project}_${run.name}` });

  // ---- yerleşim ----
  const metaEl = h("div", { class: "run-meta" });
  const stripEl = h("section", { class: "strip", "aria-label": "Anlık durum" });
  const compareEl = h("section", { class: "compare-bar", "aria-label": "Önceki eğitimlerle karşılaştır" });
  const consoleCount = h("span", { class: "count" }, "0");
  const tabButtons = new Map();
  const panels = new Map();
  const tabBar = h("div", { class: "tabs", role: "tablist", "aria-label": "Run bölümleri" }, TABS.map(([key, label]) => {
    const button = h("button", { class: "tab", type: "button", role: "tab", id: `tab-${key}`, "aria-controls": `panel-${key}`,
      "aria-selected": String(key === state.tab), onclick: () => selectTab(key) }, label, key === "console" ? consoleCount : null);
    tabButtons.set(key, button);
    return button;
  }));
  const consoleList = h("div", { class: "console", role: "log", tabindex: "0" });
  const configPanel = h("div", {});
  const resultsPanel = h("div", {});
  panels.set("charts", h("div", { id: "panel-charts", role: "tabpanel", "aria-labelledby": "tab-charts" }, board.el));
  panels.set("console", h("div", { id: "panel-console", role: "tabpanel", "aria-labelledby": "tab-console", hidden: true }, consoleToolbar(), consoleList));
  panels.set("config", h("div", { id: "panel-config", role: "tabpanel", "aria-labelledby": "tab-config", hidden: true }, configPanel));
  panels.set("results", h("div", { id: "panel-results", role: "tabpanel", "aria-labelledby": "tab-results", hidden: true }, resultsPanel));

  view.replaceChildren(
    h("section", { class: "page-head run-head" },
      h("div", {},
        h("a", { class: "back", href: "#/" }, icon("arrow-left", 14), "Eğitimler"),
        h("h1", {}, h("span", { class: "muted" }, `${run.project} / `), run.name), metaEl),
      h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", onclick: exportAll }, icon("download"), "Tümünü indir (zip)"),
        h("button", { class: "btn btn-danger-ghost", type: "button", onclick: () => confirmDelete(run, () => { location.hash = "#/"; }) }, icon("trash"), "Sil"))),
    stripEl, compareEl, tabBar, ...panels.values());

  // ---- çizimler ----
  function drawMeta() {
    const r = state.run;
    metaEl.replaceChildren(statusBadge(r.status), ...[r.host, r.seed != null ? `seed ${r.seed}` : null,
      `başladı ${fmtDate(r.started_at)}`, r.ended_at ? `bitti ${fmtDate(r.ended_at)}` : null, SOURCE[r.source]]
      .filter(Boolean).map((t) => h("span", {}, "· ", t)));
  }

  function lastValue(candidates) {
    const key = pickKey(Object.keys(state.points), candidates);
    const pts = key && state.points[key];
    return pts?.length ? pts[pts.length - 1][1] : null;
  }

  function tile(label, value, subs = [], { progress = null, wide = false, delta = 0 } = {}) {
    return h("div", { class: `tile${wide ? " tile-wide" : ""}` },
      h("div", { class: "tile-label" }, label),
      h("div", { class: "tile-value mono" }, value),
      progress != null ? h("div", { class: "progress-track" }, h("div", { class: "progress-fill", style: `width:${progress}%` })) : null,
      subs.filter(Boolean).map((s) => h("div", { class: `tile-sub${delta > 0 ? " up" : delta < 0 ? " down" : ""}` }, s)));
  }

  function drawStrip() {
    const keys = Object.keys(state.points);
    const rewardKey = pickKey(keys, CORE_KEYS.reward);
    const rewardPts = rewardKey ? state.points[rewardKey] : [];
    let best = null;
    for (const p of rewardPts) if (best == null || p[1] > best) best = p[1];
    const fps = lastValue(CORE_KEYS.fps);
    const p = progressInfo(state.run, fps);
    let delta = null, deltaRef = null;
    if (rewardKey && state.refs.length) {
      for (const ref of state.refs) {
        const refPts = ref.points[rewardKey];
        if (!refPts?.length) continue;
        delta = deltaAtStep(toXY(rewardPts, "step"), toXY(refPts, "step"));
        if (delta) { deltaRef = ref.run.name; break; }
      }
    }
    const success = lastValue(CORE_KEYS.success);
    const deltaText = delta
      ? `${delta.diff >= 0 ? "+" : ""}${formatNum(delta.diff, 3)}${delta.pct != null ? ` (%${Math.abs(delta.pct).toFixed(1)} ${delta.diff >= 0 ? "önde" : "geride"})` : ""} · ${deltaRef} ile aynı adımda`
      : null;
    stripEl.replaceChildren(
      tile("İlerleme", p.pct != null ? `%${p.pct.toFixed(1)}` : formatCompact(p.cur), [
        p.total ? `${formatCompact(p.cur)} / ${formatCompact(p.total)} adım` : "toplam adım bilinmiyor",
        p.eta != null ? `kalan ~${formatDuration(p.eta)}` : null,
        fps != null ? `${formatNum(fps, 3)} adım/sn` : null,
      ], { progress: p.pct, wide: true }),
      tile("Anlık reward", formatNum(lastValue(CORE_KEYS.reward)), [deltaText || (rewardKey ? rewardKey : "reward loglanmadı")],
        { delta: delta ? Math.sign(delta.diff) : 0 }),
      tile("En iyi reward", formatNum(best)),
      tile("Episode uzunluğu", formatNum(lastValue(CORE_KEYS.epLen))),
      tile("Başarı oranı", success == null ? "—" : `%${(success * 100).toFixed(1)}`),
      tile("Learning rate", formatNum(lastValue(CORE_KEYS.lr))),
      tile("Geçen süre", formatDuration(p.elapsed)));
  }

  function drawCompareBar() {
    const used = new Set([run.id, ...state.refs.map((r) => r.run.id)]);
    const candidates = others().filter((r) => !used.has(r.id));
    const sameProject = candidates.filter((r) => r.project === run.project);
    const byProject = new Map();
    for (const r of [...sameProject, ...candidates.filter((r) => r.project !== run.project)]) {
      if (!byProject.has(r.project)) byProject.set(r.project, []);
      byProject.get(r.project).push(r);
    }
    const select = h("select", { "aria-label": "Referans run ekle", onchange: async (e) => {
      const rid = Number(e.target.value);
      e.target.value = "";
      if (rid) await addRef(rid);
    } }, h("option", { value: "" }, "+ Run ekle…"),
      [...byProject.entries()].map(([project, runs]) => h("optgroup", { label: project },
        runs.map((r) => h("option", { value: String(r.id) }, `${r.name} · ${STATUS[r.status] || r.status} · ${fmtDate(r.started_at)}`)))));
    const quick = [
      ["Son run", () => sameProject.filter((r) => r.status !== "running").slice(0, 1)],
      ["En iyi run", () => {
        const scored = sameProject.filter((r) => r.last_reward != null).sort((a, b) => b.last_reward - a.last_reward);
        return scored.slice(0, 1);
      }],
      ["Aynı grup", () => sameProject.filter((r) => groupKey(r.name) === groupKey(run.name)).slice(0, 8)],
    ];
    compareEl.replaceChildren(
      h("div", { class: "compare-title" }, icon("chart", 14), "Önceki eğitimlerle karşılaştır"),
      h("div", { class: "chips" },
        h("span", { class: "chip chip-static" }, h("span", { class: "swatch", style: `background:${LIVE_COLOR}` }), "bu run"),
        state.refs.map((r) => h("span", { class: "chip" },
          h("span", { class: "swatch", style: `background:${r.color}` }),
          r.run.project === run.project ? r.run.name : `${r.run.project} / ${r.run.name}`,
          h("button", { class: "chip-x", type: "button", "aria-label": `${r.run.name} referansını kaldır`, onclick: () => removeRef(r.run.id) }, icon("x", 12))))),
      h("div", { class: "compare-actions" }, select,
        quick.map(([label, pick]) => h("button", { class: "btn btn-sm", type: "button", onclick: async () => {
          const picked = pick();
          if (!picked.length) { toast("Uygun run bulunamadı", "info"); return; }
          for (const r of picked) await addRef(r.id);
        } }, label)),
        h("label", { class: `ctl check-ctl${state.refs.length < 2 ? " disabled" : ""}`, title: "En az iki referans gerekir" },
          h("input", { type: "checkbox", checked: state.band, disabled: state.refs.length < 2,
            onchange: (e) => { state.band = e.target.checked; syncBoard(); } }),
          h("span", {}, "Ortalama ± σ"))));
  }

  function syncBoard() {
    board.setEntries([
      { run: state.run, label: `${run.name} (bu run)`, color: LIVE_COLOR, role: "primary", points: state.points },
      ...state.refs.map((r) => ({ run: r.run, label: r.run.project === run.project ? r.run.name : `${r.run.project}/${r.run.name}`,
        color: r.color, role: "ref", points: r.points })),
    ], { band: state.band });
  }

  async function addRef(rid) {
    if (rid === run.id || state.refs.some((r) => r.run.id === rid)) return;
    try {
      const meta = allRuns.find((r) => r.id === rid) || (await api.run(rid));
      const refPoints = await api.metrics(rid);
      const usedColors = new Set(state.refs.map((r) => r.color));
      const color = PALETTE.find((c) => !usedColors.has(c)) || PALETTE[state.refs.length % PALETTE.length];
      state.refs.push({ run: meta, points: refPoints, color });
      refsChanged();
    } catch (e) {
      toast(`Run #${rid} eklenemedi: ${e.message}`, "error");
    }
  }

  function removeRef(rid) {
    state.refs = state.refs.filter((r) => r.run.id !== rid);
    refsChanged();
  }

  function refsChanged() {
    if (state.refs.length < 2) state.band = false;
    const query = state.refs.length ? `?ref=${state.refs.map((r) => r.run.id).join(",")}` : "";
    history.replaceState(null, "", `#/run/${run.id}${query}`);
    drawCompareBar();
    syncBoard();
    drawStrip();
  }

  // ---- konsol ----
  function consoleToolbar() {
    const level = h("select", { "aria-label": "Log seviyesi", onchange: (e) => { state.level = e.target.value; drawConsole(); } },
      LEVELS.map((l) => h("option", { value: l }, l || "Tüm seviyeler")));
    const query = h("input", { type: "search", placeholder: "Logda ara…", "aria-label": "Logda ara",
      oninput: (e) => { state.query = e.target.value.toLowerCase(); drawConsole(); } });
    const auto = h("input", { type: "checkbox", checked: true, onchange: (e) => { state.autoscroll = e.target.checked; } });
    const save = h("button", { class: "btn btn-sm", type: "button", onclick: () => {
      const text = state.logs.map((l) => `${l.wall_time ? new Date(l.wall_time * 1000).toISOString() : "-"}\t${l.level}\t${l.line}`).join("\n");
      download(new Blob([text], { type: "text/plain;charset=utf-8" }), `${safeName(run.project)}_${safeName(run.name)}_console.log`);
    } }, icon("download", 14), "Logu indir");
    return h("div", { class: "console-toolbar" }, h("label", { class: "search" }, icon("search"), query), level,
      h("label", { class: "ctl check-ctl" }, auto, h("span", {}, "Otomatik kaydır")), save);
  }

  const matches = (l) => (!state.level || l.level === state.level) && (!state.query || String(l.line).toLowerCase().includes(state.query));
  const logRow = (l) => h("div", { class: `log-line lvl-${String(l.level || "INFO").toLowerCase()}` },
    h("span", { class: "log-time" }, l.wall_time ? new Date(l.wall_time * 1000).toLocaleTimeString("tr-TR") : ""),
    h("span", { class: "log-level" }, l.level),
    h("span", { class: "log-text" }, l.line));

  function drawConsole() {
    const rows = state.logs.filter(matches).slice(-MAX_CONSOLE_ROWS);
    consoleList.replaceChildren(...(rows.length ? rows.map(logRow)
      : [h("div", { class: "muted small", style: "padding: 0 12px" }, state.logs.length ? "Filtreyle eşleşen satır yok." : "Henüz log yok.")]));
    consoleCount.textContent = String(state.logs.length);
    if (state.autoscroll) consoleList.scrollTop = consoleList.scrollHeight;
  }

  function appendLogs(rows) {
    if (!rows.length) return;
    const wasEmpty = !state.logs.some(matches);
    state.logs.push(...rows);
    if (state.logs.length > 20_000) state.logs.splice(0, state.logs.length - 20_000);
    if (wasEmpty) { drawConsole(); return; }
    consoleList.append(...rows.filter(matches).map(logRow));
    while (consoleList.childElementCount > MAX_CONSOLE_ROWS) consoleList.firstElementChild.remove();
    consoleCount.textContent = String(state.logs.length);
    if (state.autoscroll) consoleList.scrollTop = consoleList.scrollHeight;
  }

  // ---- config / sonuçlar ----
  function kvPanel(target, obj, emptyText, fileName) {
    const rows = obj ? flatten(obj) : [];
    target.replaceChildren(...(rows.length ? [
      h("div", { class: "panel-actions" }, h("button", { class: "btn btn-sm", type: "button",
        onclick: () => download(new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" }), fileName) }, icon("download", 14), "JSON indir")),
      h("div", { class: "table-wrap" }, h("table", { class: "kv" }, h("tbody", {},
        rows.map(([k, v]) => h("tr", {}, h("th", { class: "mono", scope: "row" }, k), h("td", { class: "mono" }, v)))))),
    ] : [h("div", { class: "empty small" }, emptyText)]));
  }

  let lastConfig = "", lastResults = "";
  function drawKv() {
    const config = JSON.stringify(state.run.config), results = JSON.stringify(state.run.results);
    if (config !== lastConfig) { lastConfig = config; kvPanel(configPanel, state.run.config, "Bu run için config kaydedilmemiş.", `${safeName(run.name)}_config.json`); }
    if (results !== lastResults) { lastResults = results; kvPanel(resultsPanel, state.run.results, "Henüz sonuç yok — eğitim bitince panel.result(...) ile gönderilenler burada görünür.", `${safeName(run.name)}_results.json`); }
  }

  function selectTab(key) {
    state.tab = key;
    for (const [k, button] of tabButtons) button.setAttribute("aria-selected", String(k === key));
    for (const [k, panel] of panels) panel.hidden = k !== key;
    if (key === "console") drawConsole();
    if (key === "charts") board.redrawAll();
  }

  // ---- zip ----
  async function exportAll(e) {
    const button = e.currentTarget;
    button.disabled = true;
    toast("Zip hazırlanıyor…");
    try {
      const zip = await JSZip.loadAsync(await api.exportZip(run.id));
      for (const { name, blob } of await board.pngs()) zip.file(`grafikler/${name}`, blob);
      download(await zip.generateAsync({ type: "blob" }), `${safeName(run.project)}_${safeName(run.name)}.zip`);
    } catch (err) {
      toast(`Zip oluşturulamadı: ${err.message}`, "error");
    } finally {
      button.disabled = false;
    }
  }

  // ---- canlı ----
  async function reloadAll() {
    try {
      const [fresh, freshPoints, freshLogs] = await Promise.all([api.run(run.id), api.metrics(run.id), api.logs(run.id, { tail: 5000 })]);
      Object.assign(state.run, fresh);
      board.reload(run.id, freshPoints);
      state.logs = freshLogs;
      drawMeta(); drawStrip(); drawKv(); drawConsole();
    } catch { /* sunucu henüz dönmedi; sonraki yeniden bağlanmada tekrar denenir */ }
  }

  const off = onEvent((ev) => {
    if ((ev.type === "run" || ev.type === "batch") && ev.run) {
      if (ev.run.id === run.id) {
        Object.assign(state.run, ev.run);
        if (ev.type === "batch") {
          if (ev.reset) { reloadAll(); return; }
          board.appendPoints(run.id, ev.metrics);  // state.points ile aynı nesne: tek yerde eklenir
          appendLogs(ev.logs || []);
        }
        drawMeta(); drawStrip(); drawKv();
      } else {
        const ref = state.refs.find((r) => r.run.id === ev.run.id);
        if (ref) {
          Object.assign(ref.run, ev.run);
          if (ev.type === "batch" && ev.metrics.length) { board.appendPoints(ref.run.id, ev.metrics); drawStrip(); }
        }
        const known = allRuns.find((r) => r.id === ev.run.id);
        if (known) Object.assign(known, ev.run); else allRuns.push(ev.run);
      }
    } else if (ev.type === "deleted") {
      if (ev.run_id === run.id) { toast("Bu run silindi", "info"); location.hash = "#/"; return; }
      if (state.refs.some((r) => r.run.id === ev.run_id)) removeRef(ev.run_id);
      allRuns = allRuns.filter((r) => r.id !== ev.run_id);
    } else if (ev.type === "reconnected") {
      reloadAll();
    }
  });
  const ticker = setInterval(() => { if (state.run.status === "running") drawStrip(); }, 1000);

  drawMeta();
  drawKv();
  syncBoard();
  drawStrip();
  drawCompareBar();
  drawConsole();
  const refIds = (params.get("ref") || "").split(",").map(Number).filter((n) => n && n !== run.id);
  for (const rid of refIds) await addRef(rid);

  return () => { off(); clearInterval(ticker); board.destroy(); };
}
