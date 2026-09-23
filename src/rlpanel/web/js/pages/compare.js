import { api } from "../api.js";
import { MetricBoard } from "../board.js";
import { LIVE_COLOR, PALETTE } from "../charts.js";
import { onEvent } from "../live.js";
import { STATUS, fmtDate, h, icon, toast } from "../ui.js";

const COLORS = [LIVE_COLOR, ...PALETTE];

export async function renderCompare(view, params) {
  let allRuns;
  try { allRuns = await api.runs(); }
  catch (e) { view.replaceChildren(h("div", { class: "empty" }, h("h2", {}, "Run listesi alınamadı"), h("p", {}, e.message))); return () => {}; }

  const state = { entries: [], band: false };
  const board = new MetricBoard({ keysFrom: "all", bandRole: "peer", fileBase: "karsilastirma" });
  const bar = h("section", { class: "compare-bar", "aria-label": "Karşılaştırılan run'lar" });
  const hint = h("div", { class: "empty small" }, "Karşılaştırmak için en az iki run ekle.");
  view.replaceChildren(
    h("section", { class: "page-head" }, h("div", {}, h("h1", {}, "Karşılaştır"),
      h("p", { class: "sub" }, "Seçtiğin run'ların aynı metrikleri üst üste çizilir; tek tek ya da ortalama ± σ olarak."))),
    bar, hint, board.el);

  function label(run) {
    const sameProject = state.entries.every((e) => e.run.project === run.project);
    return sameProject ? run.name : `${run.project}/${run.name}`;
  }

  function sync() {
    for (const e of state.entries) e.label = label(e.run);
    if (state.entries.length < 2) state.band = false;
    hint.hidden = state.entries.length >= 2;
    history.replaceState(null, "", `#/compare${state.entries.length ? `?ids=${state.entries.map((e) => e.run.id).join(",")}` : ""}`);
    drawBar();
    board.setEntries(state.entries, { band: state.band });
  }

  function drawBar() {
    const used = new Set(state.entries.map((e) => e.run.id));
    const byProject = new Map();
    for (const r of allRuns.filter((r) => !used.has(r.id))) {
      if (!byProject.has(r.project)) byProject.set(r.project, []);
      byProject.get(r.project).push(r);
    }
    bar.replaceChildren(
      h("div", { class: "chips" }, state.entries.map((e) => h("span", { class: "chip" },
        h("span", { class: "swatch", style: `background:${e.color}` }), e.label,
        h("button", { class: "chip-x", type: "button", "aria-label": `${e.run.name} çıkar`, onclick: () => remove(e.run.id) }, icon("x", 12))))),
      h("div", { class: "compare-actions" },
        h("select", { "aria-label": "Run ekle", onchange: async (ev) => { const id = Number(ev.target.value); ev.target.value = ""; if (id) await add(id); } },
          h("option", { value: "" }, "+ Run ekle…"),
          [...byProject.entries()].map(([project, runs]) => h("optgroup", { label: project },
            runs.map((r) => h("option", { value: String(r.id) }, `${r.name} · ${STATUS[r.status] || r.status} · ${fmtDate(r.started_at)}`))))),
        h("label", { class: `ctl check-ctl${state.entries.length < 2 ? " disabled" : ""}` },
          h("input", { type: "checkbox", checked: state.band, disabled: state.entries.length < 2,
            onchange: (ev) => { state.band = ev.target.checked; board.setEntries(state.entries, { band: state.band }); } }),
          h("span", {}, "Ortalama ± σ"))));
  }

  async function add(id, silent = false) {
    if (state.entries.some((e) => e.run.id === id)) return;
    try {
      const run = allRuns.find((r) => r.id === id) || (await api.run(id));
      const points = await api.metrics(id);
      const usedColors = new Set(state.entries.map((e) => e.color));
      const color = COLORS.find((c) => !usedColors.has(c)) || COLORS[state.entries.length % COLORS.length];
      state.entries.push({ run, label: run.name, color, role: "peer", points });
      if (!silent) sync();
    } catch (e) {
      toast(`Run #${id} eklenemedi: ${e.message}`, "error");
    }
  }

  function remove(id) {
    state.entries = state.entries.filter((e) => e.run.id !== id);
    sync();
  }

  const off = onEvent((ev) => {
    if (ev.type === "batch" && ev.run && state.entries.some((e) => e.run.id === ev.run.id)) {
      if (ev.reset) {
        api.metrics(ev.run.id).then((points) => board.reload(ev.run.id, points)).catch(() => {});
      } else {
        board.appendPoints(ev.run.id, ev.metrics);
      }
    } else if (ev.type === "run" && ev.run && !allRuns.some((r) => r.id === ev.run.id)) {
      allRuns.push(ev.run);
      drawBar();
    } else if (ev.type === "deleted") {
      allRuns = allRuns.filter((r) => r.id !== ev.run_id);
      if (state.entries.some((e) => e.run.id === ev.run_id)) remove(ev.run_id); else drawBar();
    }
  });

  for (const id of (params.get("ids") || "").split(",").map(Number).filter(Boolean)) await add(id, true);
  sync();
  return () => { off(); board.destroy(); };
}
