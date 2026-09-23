import { alignSeries, chartSVG, ema, formatCompact, formatNum, meanStd, toCSV, toXY } from "./core.js";

export const LIVE_COLOR = "#22C55E";
export const PALETTE = ["#60A5FA", "#F59E0B", "#A78BFA", "#F472B6", "#2DD4BF", "#FB923C", "#E879F9", "#94A3B8"];
const EXPORT_THEME = { bg: "#FFFFFF", text: "#0F172A", muted: "#64748B", grid: "#E2E8F0" };

const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function withAlpha(hex, alpha) {
  if (!/^#[0-9a-f]{6}$/i.test(hex) || alpha >= 1) return hex;
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function shortDuration(sec) {
  if (sec < 60) return `${Math.round(sec)}sn`;
  if (sec < 3600) return `${Math.round(sec / 60)}dk`;
  return `${(sec / 3600).toFixed(1).replace(/\.0$/, "")}sa`;
}

export function buildModel(lines, opts = {}) {
  const xmode = opts.xmode || "step";
  const smoothing = opts.smoothing || 0;
  const prepared = lines.map((line) => {
    const { xs, ys } = toXY(line.points, xmode);
    return { ...line, xs, rawYs: ys, ys: ema(ys, smoothing) };
  });
  let band = null;
  if (opts.band) {
    const sources = opts.band.sources.map((points) => {
      const { xs, ys } = toXY(points, xmode);
      return { xs, ys: ema(ys, smoothing) };
    });
    const stats = meanStd(sources);
    if (stats) band = { ...stats, color: opts.band.color, label: opts.band.label };
  }
  const positive = (arr) => arr.every((v) => v == null || v > 0);
  const log = !!opts.log && prepared.every((l) => positive(l.ys)) && (!band || positive(band.lo));
  return { lines: prepared, band, xmode, log, logRequested: !!opts.log };
}

export function modelCSV(model) {
  const header = [model.xmode === "time" ? "sure_sn" : "adim"];
  const sources = [];
  const smoothed = model.lines.some((l) => l.ys.some((v, i) => v !== l.rawYs[i]));
  for (const line of model.lines) {
    header.push(line.label);
    sources.push({ xs: line.xs, ys: line.ys });
    if (smoothed) { header.push(`${line.label} (ham)`); sources.push({ xs: line.xs, ys: line.rawYs }); }
  }
  if (model.band) {
    header.push(`${model.band.label} ort`, `${model.band.label} -1σ`, `${model.band.label} +1σ`);
    sources.push({ xs: model.band.xs, ys: model.band.mean }, { xs: model.band.xs, ys: model.band.lo }, { xs: model.band.xs, ys: model.band.hi });
  }
  const data = alignSeries(sources);
  const rows = data[0].map((x, i) => [x, ...data.slice(1).map((col) => col[i])]);
  return toCSV(header, rows);
}

export function modelSVG(model, title) {
  const series = model.lines.map((l) => ({ label: l.label, color: l.color, xs: l.xs, ys: l.ys,
    width: (l.width ?? 1.5) * 1.4, opacity: l.opacity ?? 1, dash: l.dash }));
  let band = null;
  if (model.band) {
    band = { xs: model.band.xs, lo: model.band.lo, hi: model.band.hi, color: model.band.color };
    series.push({ label: `${model.band.label} (ort.)`, color: model.band.color, xs: model.band.xs, ys: model.band.mean, width: 2, dash: [8, 5] });
  }
  return chartSVG({ title, xLabel: model.xmode === "time" ? "süre (sn)" : "adım", series, band, log: model.log, theme: EXPORT_THEME });
}

export async function svgToPng(svg, scale = 2) {
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const img = new Image();
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = () => reject(new Error("SVG çizilemedi"));
      img.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = img.width * scale;
    canvas.height = img.height * scale;
    const ctx = canvas.getContext("2d");
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    return await new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("PNG oluşturulamadı"))), "image/png"));
  } finally {
    URL.revokeObjectURL(url);
  }
}

export class MetricChart {
  constructor(container, { title, height = 240 }) {
    this.container = container;
    this.title = title;
    this.height = height;
    this.u = null;
    this.model = null;
    this.signature = "";
    this.observer = new ResizeObserver(() => {
      if (!this.u) return;
      const width = this.width();
      if (width !== this.u.width) this.u.setSize({ width, height: this.height });
    });
    this.observer.observe(container);
  }

  width() {
    return Math.max(240, Math.floor(this.container.clientWidth));
  }

  update(lines, opts) {
    const model = buildModel(lines, opts);
    this.model = model;
    const sources = model.lines.map((l) => ({ xs: l.xs, ys: l.ys }));
    if (model.band) sources.push({ xs: model.band.xs, ys: model.band.mean }, { xs: model.band.xs, ys: model.band.hi }, { xs: model.band.xs, ys: model.band.lo });
    const data = alignSeries(sources);
    if (model.log) for (let i = 1; i < data.length; i++) data[i] = data[i].map((v) => (v != null && v > 0 ? v : null));
    const signature = JSON.stringify([model.lines.map((l) => [l.label, l.color, l.width, l.opacity]), !!model.band,
      model.log, model.xmode, cssVar("--chart-axis")]);
    if (this.u && signature === this.signature) {
      this.u.setData(data);
    } else {
      this.signature = signature;
      this.u?.destroy();
      this.u = new uPlot(this.options(model), data, this.container);
    }
    this.container.title = model.logRequested && !model.log ? "Log ölçek kapalı: grafikte sıfır/negatif değer var" : "";
  }

  options(model) {
    const axis = cssVar("--chart-axis"), grid = cssVar("--chart-grid");
    const font = `11px ${cssVar("--font-mono") || "monospace"}`;
    const series = [{
      label: model.xmode === "time" ? "süre" : "adım",
      value: (u, v) => (v == null ? "—" : model.xmode === "time" ? shortDuration(v) : formatCompact(v)),
    }];
    for (const l of model.lines) {
      series.push({ label: l.label, stroke: withAlpha(l.color, l.opacity ?? 1), width: l.width ?? 1.5, dash: l.dash,
        spanGaps: true, points: { show: false }, value: (u, v) => formatNum(v) });
    }
    const bands = [];
    if (model.band) {
      const base = series.length;
      series.push({ label: `${model.band.label} (ort.)`, stroke: model.band.color, width: 1.5, dash: [6, 4], spanGaps: true, points: { show: false }, value: (u, v) => formatNum(v) });
      series.push({ label: "+1σ", stroke: "transparent", width: 0, spanGaps: true, points: { show: false }, value: (u, v) => formatNum(v) });
      series.push({ label: "−1σ", stroke: "transparent", width: 0, spanGaps: true, points: { show: false }, value: (u, v) => formatNum(v) });
      bands.push({ series: [base + 1, base + 2], fill: withAlpha(model.band.color, 0.16) });
    }
    const axisBase = { stroke: axis, font, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 } };
    return {
      width: this.width(),
      height: this.height,
      series,
      bands,
      scales: { x: { time: false }, y: model.log ? { distr: 3 } : {} },
      axes: [
        { ...axisBase, values: (u, vals) => vals.map((v) => (model.xmode === "time" ? shortDuration(v) : formatCompact(v))) },
        { ...axisBase, size: 60, values: (u, vals) => vals.map((v) => formatNum(v, 3)) },
      ],
      legend: { live: true },
      cursor: { drag: { x: true, y: false }, points: { size: 6 } },
    };
  }

  destroy() {
    this.observer.disconnect();
    this.u?.destroy();
    this.u = null;
  }
}
