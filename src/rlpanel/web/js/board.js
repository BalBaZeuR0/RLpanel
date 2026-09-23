import { MetricChart, buildModel, modelCSV, modelSVG, svgToPng } from "./charts.js";
import { groupMetricKeys, safeName } from "./core.js";
import { download, h, icon, toast } from "./ui.js";

const SETTINGS_KEY = "rlpanel-board";
const DEFAULTS = { smoothing: 0.6, xmode: "step", log: false };
const BAND_COLOR = "#94A3B8";

function loadSettings() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") }; }
  catch { return { ...DEFAULTS }; }
}

export class MetricBoard {
  constructor({ keysFrom = "primary", bandRole = "ref", fileBase = "rlpanel" } = {}) {
    this.keysFrom = keysFrom;
    this.bandRole = bandRole;
    this.fileBase = fileBase;
    this.settings = loadSettings();
    this.filter = "";
    this.entries = [];
    this.band = false;
    this.charts = new Map();
    this.dirty = new Set();
    this.timer = null;
    this.layout = "";
    this.groupsEl = h("div", { class: "chart-groups" });
    this.el = h("div", { class: "board" }, this.toolbar(), this.groupsEl);
    this.onTheme = () => { this.layout = ""; this.render(); };
    window.addEventListener("rlpanel-theme", this.onTheme);
  }

  toolbar() {
    const seg = h("div", { class: "segmented", role: "group", "aria-label": "X ekseni" },
      [["step", "Adım"], ["time", "Süre"]].map(([value, label]) => h("button", {
        class: "seg", type: "button", "aria-pressed": String(this.settings.xmode === value),
        onclick: (e) => {
          this.settings.xmode = value;
          seg.querySelectorAll(".seg").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
          this.save();
          this.redrawAll();
        },
      }, label)));
    const smoothOut = h("output", { class: "mono small" }, this.settings.smoothing.toFixed(2));
    const smooth = h("input", { type: "range", min: "0", max: "0.99", step: "0.01", value: String(this.settings.smoothing), "aria-label": "Yumuşatma",
      oninput: (e) => { this.settings.smoothing = Number(e.target.value); smoothOut.textContent = this.settings.smoothing.toFixed(2); this.save(); this.scheduleAll(); } });
    const log = h("input", { type: "checkbox", checked: this.settings.log,
      onchange: (e) => { this.settings.log = e.target.checked; this.save(); this.redrawAll(); } });
    const filter = h("input", { type: "search", placeholder: "Metrik filtrele…", "aria-label": "Metrik filtrele",
      oninput: (e) => { this.filter = e.target.value.toLowerCase(); this.render(); } });
    return h("div", { class: "board-toolbar" },
      h("div", { class: "ctl" }, h("span", { class: "ctl-label" }, "X ekseni"), seg),
      h("label", { class: "ctl" }, h("span", { class: "ctl-label" }, "Yumuşatma"), smooth, smoothOut),
      h("label", { class: "ctl check-ctl" }, log, h("span", {}, "Log ölçek")),
      h("label", { class: "search ctl-grow" }, icon("search"), filter));
  }

  save() {
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(this.settings)); } catch { /* tarayıcı depolaması kapalı */ }
  }

  setEntries(entries, { band = false } = {}) {
    this.entries = entries;
    this.band = band;
    this.layout = "";
    this.render();
  }

  appendPoints(runId, metrics) {
    const entry = this.entries.find((e) => e.run.id === runId);
    if (!entry || !metrics.length) return;
    let newKey = false;
    for (const [key, step, value, wall] of metrics) {
      if (!entry.points[key]) { entry.points[key] = []; newKey = true; }
      entry.points[key].push([step, value, wall]);
      this.dirty.add(key);
    }
    if (newKey) this.render(); else this.schedule();
  }

  reload(runId, points) {
    const entry = this.entries.find((e) => e.run.id === runId);
    if (!entry) return;
    for (const key of Object.keys(entry.points)) delete entry.points[key];
    Object.assign(entry.points, points);
    this.layout = "";
    this.render();
  }

  keys() {
    const source = this.keysFrom === "primary" ? this.entries.filter((e) => e.role === "primary") : this.entries;
    const keys = new Set();
    for (const e of source) for (const k of Object.keys(e.points)) keys.add(k);
    return [...keys];
  }

  render() {
    const keys = this.keys().filter((k) => !this.filter || k.toLowerCase().includes(this.filter));
    const groups = groupMetricKeys(keys);
    const layout = JSON.stringify(groups);
    if (layout !== this.layout) {
      this.layout = layout;
      for (const chart of this.charts.values()) chart.destroy();
      this.charts.clear();
      if (!groups.length) {
        this.groupsEl.replaceChildren(h("div", { class: "empty small" }, this.filter
          ? "Filtreyle eşleşen metrik yok."
          : "Henüz metrik gelmedi — eğitim ilk logunu yazınca grafikler burada belirir."));
        return;
      }
      this.groupsEl.replaceChildren(...groups.map((g) => h("section", { class: "chart-group" },
        h("h3", {}, g.title, h("span", { class: "count" }, g.keys.length)),
        h("div", { class: "chart-grid" }, g.keys.map((k) => this.card(k))))));
    }
    this.redrawAll();
  }

  card(key) {
    const body = h("div", { class: "chart-body" });
    const card = h("article", { class: "chart-card", dataset: { key } },
      h("header", {}, h("h4", { class: "mono", title: key }, key),
        h("div", { class: "chart-actions" },
          h("button", { class: "mini-btn", type: "button", title: "PNG indir", "aria-label": `${key} PNG indir`, onclick: () => this.downloadChart(key, "png") }, icon("image", 13), "PNG"),
          h("button", { class: "mini-btn", type: "button", title: "SVG indir", "aria-label": `${key} SVG indir`, onclick: () => this.downloadChart(key, "svg") }, "SVG"),
          h("button", { class: "mini-btn", type: "button", title: "CSV indir", "aria-label": `${key} CSV indir`, onclick: () => this.downloadChart(key, "csv") }, "CSV"))),
      body);
    this.charts.set(key, new MetricChart(body, { title: key }));
    return card;
  }

  linesFor(key) {
    const bandSources = this.entries.filter((e) => e.role === this.bandRole && e.points[key]?.length);
    const useBand = this.band && bandSources.length >= 2;
    const lines = [];
    for (const e of this.entries) {
      const points = e.points[key];
      if (!points?.length) continue;
      if (useBand && e.role === this.bandRole) continue;
      lines.push({ label: e.label, color: e.color, points,
        width: e.role === "primary" ? 2.25 : e.role === "peer" ? 1.75 : 1.5,
        opacity: e.role === "ref" ? 0.6 : 1 });
    }
    const band = useBand ? { label: this.bandRole === "ref" ? "Referans ort. ± σ" : "Ortalama ± σ", color: BAND_COLOR,
      sources: bandSources.map((e) => e.points[key]) } : null;
    return { lines, band };
  }

  options(band) {
    return { smoothing: this.settings.smoothing, xmode: this.settings.xmode, log: this.settings.log, band };
  }

  redrawAll() {
    for (const key of this.charts.keys()) this.dirty.add(key);
    this.flush();
  }

  scheduleAll() {
    for (const key of this.charts.keys()) this.dirty.add(key);
    this.schedule();
  }

  schedule() {
    if (this.timer) return;
    this.timer = setTimeout(() => { this.timer = null; this.flush(); }, 400);
  }

  flush() {
    for (const key of this.dirty) {
      const chart = this.charts.get(key);
      if (!chart) continue;
      const { lines, band } = this.linesFor(key);
      chart.update(lines, this.options(band));
    }
    this.dirty.clear();
  }

  exportModel(key) {
    const { lines, band } = this.linesFor(key);
    return buildModel(lines, this.options(band));
  }

  async downloadChart(key, kind) {
    const base = `${safeName(this.fileBase)}_${safeName(key)}`;
    try {
      const model = this.exportModel(key);
      if (kind === "csv") download(new Blob([modelCSV(model)], { type: "text/csv;charset=utf-8" }), `${base}.csv`);
      else if (kind === "svg") download(new Blob([modelSVG(model, key)], { type: "image/svg+xml" }), `${base}.svg`);
      else download(await svgToPng(modelSVG(model, key)), `${base}.png`);
    } catch (e) {
      toast(`İndirilemedi: ${e.message}`, "error");
    }
  }

  async pngs() {
    const out = [];
    for (const key of this.keys()) out.push({ name: `${safeName(key)}.png`, blob: await svgToPng(modelSVG(this.exportModel(key), key)) });
    return out;
  }

  destroy() {
    clearTimeout(this.timer);
    window.removeEventListener("rlpanel-theme", this.onTheme);
    for (const chart of this.charts.values()) chart.destroy();
    this.charts.clear();
  }
}
