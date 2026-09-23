// Saf yardımcılar: DOM bilmez, tarayıcıda test edilir (tests/e2e/test_core_js.py).

export const REWARD_KEYS = ["rollout/ep_rew_mean", "eval/mean_reward", "reward", "ep_reward", "episode_reward"];
export const CORE_KEYS = {
  reward: REWARD_KEYS,
  epLen: ["rollout/ep_len_mean", "eval/mean_ep_length", "ep_len", "episode_length"],
  success: ["rollout/success_rate", "eval/success_rate", "success_rate"],
  lr: ["train/learning_rate", "learning_rate", "lr"],
  fps: ["time/fps", "fps"],
};

export function pickKey(keys, candidates) {
  const set = new Set(keys);
  return candidates.find((k) => set.has(k)) ?? null;
}

export function groupMetricKeys(keys) {
  const core = [CORE_KEYS.reward, CORE_KEYS.epLen, CORE_KEYS.success, CORE_KEYS.lr]
    .map((c) => pickKey(keys, c)).filter(Boolean);
  const used = new Set(core);
  const groups = new Map();
  for (const key of [...keys].sort()) {
    if (used.has(key)) continue;
    const i = key.indexOf("/");
    const title = i > 0 ? key.slice(0, i) : "Özel";
    if (!groups.has(title)) groups.set(title, []);
    groups.get(title).push(key);
  }
  const titles = [...groups.keys()].sort((a, b) => (a === "Özel") - (b === "Özel") || a.localeCompare(b));
  const out = core.length ? [{ title: "Temel", keys: core }] : [];
  for (const title of titles) out.push({ title, keys: groups.get(title) });
  return out;
}

// TensorBoard tarzı, başlangıç yanlılığı düzeltilmiş üstel ortalama. null değerler olduğu gibi geçer.
export function ema(values, weight) {
  if (!(weight > 0)) return values.slice();
  const out = new Array(values.length);
  let last = 0, n = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null || !Number.isFinite(v)) { out[i] = v ?? null; continue; }
    last = last * weight + (1 - weight) * v;
    n += 1;
    out[i] = last / (1 - Math.pow(weight, n));
  }
  return out;
}

export function interpAt(xs, ys, x) {
  const n = xs.length;
  if (!n || x < xs[0] || x > xs[n - 1]) return null;
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= x) lo = mid; else hi = mid;
  }
  if (xs[lo] === x) return ys[lo];
  if (xs[hi] === x) return ys[hi];
  const t = (x - xs[lo]) / (xs[hi] - xs[lo]);
  return ys[lo] + t * (ys[hi] - ys[lo]);
}

// points: [[step, value, wall_time]] -> {xs, ys}; "time" modunda x = ilk zamandan beri geçen saniye.
export function toXY(points, xmode = "step") {
  const first = points.find((p) => p[2] != null);
  const useTime = xmode === "time" && first != null;
  const byX = new Map();
  for (const p of points) {
    const x = useTime ? (p[2] != null ? p[2] - first[2] : null) : p[0];
    if (x != null) byX.set(x, p[1]);
  }
  const xs = [...byX.keys()].sort((a, b) => a - b);
  return { xs, ys: xs.map((x) => byX.get(x)) };
}

export function alignSeries(series) {
  const all = new Set();
  for (const s of series) for (const x of s.xs) all.add(x);
  const xs = [...all].sort((a, b) => a - b);
  const index = new Map(xs.map((x, i) => [x, i]));
  const out = [xs];
  for (const s of series) {
    const col = new Array(xs.length).fill(null);
    s.xs.forEach((x, i) => { col[index.get(x)] = s.ys[i]; });
    out.push(col);
  }
  return out;
}

export function meanStd(series, n = 200) {
  const valid = series.filter((s) => s.xs.length);
  if (valid.length < 2) return null;
  const start = Math.max(...valid.map((s) => s.xs[0]));
  const end = Math.min(...valid.map((s) => s.xs[s.xs.length - 1]));
  if (!(end > start)) return null;
  const xs = [], mean = [], lo = [], hi = [];
  for (let i = 0; i < n; i++) {
    const x = start + ((end - start) * i) / (n - 1);
    const vals = valid.map((s) => interpAt(s.xs, s.ys, x)).filter((v) => v != null && Number.isFinite(v));
    if (!vals.length) continue;
    const m = vals.reduce((a, b) => a + b, 0) / vals.length;
    const sd = Math.sqrt(vals.reduce((a, b) => a + (b - m) ** 2, 0) / vals.length);
    xs.push(x); mean.push(m); lo.push(m - sd); hi.push(m + sd);
  }
  return { xs, mean, lo, hi };
}

// Canlı run'ın son adımındaki değeri, referansın aynı adımdaki (ara değerlenmiş) değeriyle karşılaştırır.
export function deltaAtStep(live, ref) {
  if (!live.xs.length || !ref.xs.length) return null;
  const x = live.xs[live.xs.length - 1];
  const value = live.ys[live.ys.length - 1];
  const r = interpAt(ref.xs, ref.ys, x);
  if (r == null) return null;
  const diff = value - r;
  return { x, value, ref: r, diff, pct: r !== 0 ? (diff / Math.abs(r)) * 100 : null };
}

export function groupKey(name) {
  return String(name).replace(/[\s_\-/]*seed[\s_\-]*\d+$/i, "").replace(/[\s_\-]+\d+$/, "");
}

export function formatNum(v, digits = 4) {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e6 || a < 1e-3)) return v.toExponential(2);
  if (Number.isInteger(v)) return v.toLocaleString("tr-TR");
  return Number(v.toPrecision(digits)).toLocaleString("tr-TR", { maximumFractionDigits: 6 });
}

export function formatCompact(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  const trim = (s) => s.replace(/\.?0+$/, "");
  if (a >= 1e9) return trim((n / 1e9).toFixed(2)) + "B";
  if (a >= 1e6) return trim((n / 1e6).toFixed(2)) + "M";
  if (a >= 1e3) return trim((n / 1e3).toFixed(1)) + "k";
  return String(Math.round(n));
}

export function formatDuration(sec) {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return "—";
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (h) return `${h}sa ${m}dk`;
  if (m) return `${m}dk ${s}sn`;
  return `${s}sn`;
}

export function progressInfo(run, fps, now = Date.now() / 1000) {
  const total = run.total_steps || null;
  const cur = run.current_step ?? 0;
  const pct = total ? Math.min(100, (cur / total) * 100) : null;
  const elapsed = (run.ended_at ?? now) - run.started_at;
  let eta = null;
  if (total && run.status === "running" && cur < total) {
    if (fps && fps > 0) eta = (total - cur) / fps;
    else if (cur > 0) eta = (elapsed * (total - cur)) / cur;
  }
  return { pct, cur, total, elapsed, eta };
}

export function flatten(obj, prefix = "", out = []) {
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    const keys = Object.keys(obj);
    if (!keys.length && prefix) out.push([prefix, "{}"]);
    for (const k of keys) flatten(obj[k], prefix ? `${prefix}.${k}` : k, out);
  } else {
    out.push([prefix, Array.isArray(obj) ? JSON.stringify(obj) : obj === null ? "null" : String(obj)]);
  }
  return out;
}

export function toCSV(header, rows) {
  const esc = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [header, ...rows].map((r) => r.map(esc).join(",")).join("\n") + "\n";
}

export function safeName(s) {
  return String(s).replace(/[^\p{L}\p{N}._-]+/gu, "_").replace(/^_+|_+$/g, "") || "grafik";
}

export function niceTicks(min, max, count = 5) {
  if (!(max > min)) { const d = Math.abs(min) || 1; min -= d / 2; max += d / 2; }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step * 1e-9; v += step) ticks.push(Number(v.toPrecision(12)));
  return { min: lo, max: hi, ticks };
}

const escXml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Bağımsız SVG çizimi (indirme için). series: [{label, color, xs, ys, width, opacity, dash}], band: {xs, lo, hi, color}
export function chartSVG({ title = "", width = 1200, height = 640, xLabel = "adım", series = [], band = null, log = false, theme = {} }) {
  const th = { bg: "#FFFFFF", text: "#0F172A", muted: "#64748B", grid: "#E2E8F0", font: "IBM Plex Sans, Segoe UI, sans-serif", ...theme };
  const legendRows = Math.ceil(series.length / 3);
  const m = { l: 72, r: 24, t: 48, b: 64 + legendRows * 20 };
  const pw = width - m.l - m.r, ph = height - m.t - m.b;
  const fy = (v) => (v == null || !Number.isFinite(v) ? null : log ? (v > 0 ? Math.log10(v) : null) : v);
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
  const consider = (xs, ys) => xs.forEach((x, i) => {
    const y = fy(ys[i]);
    if (y == null) return;
    xmin = Math.min(xmin, x); xmax = Math.max(xmax, x); ymin = Math.min(ymin, y); ymax = Math.max(ymax, y);
  });
  series.forEach((s) => consider(s.xs, s.ys));
  if (band) { consider(band.xs, band.lo); consider(band.xs, band.hi); }
  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" font-family="${escXml(th.font)}">`,
    `<rect width="100%" height="100%" fill="${th.bg}"/>`,
    `<text x="${m.l}" y="30" font-size="18" font-weight="600" fill="${th.text}">${escXml(title)}</text>`,
  ];
  if (!Number.isFinite(xmin)) {
    parts.push(`<text x="${width / 2}" y="${height / 2}" text-anchor="middle" font-size="14" fill="${th.muted}">veri yok</text></svg>`);
    return parts.join("");
  }
  const xt = niceTicks(xmin, xmax), yt = niceTicks(ymin, ymax);
  const sx = (x) => m.l + ((x - xt.min) / (xt.max - xt.min)) * pw;
  const sy = (y) => m.t + ph - ((y - yt.min) / (yt.max - yt.min)) * ph;
  for (const t of yt.ticks) {
    const y = sy(t).toFixed(1);
    parts.push(`<line x1="${m.l}" x2="${m.l + pw}" y1="${y}" y2="${y}" stroke="${th.grid}"/>`);
    parts.push(`<text x="${m.l - 10}" y="${(sy(t) + 4).toFixed(1)}" text-anchor="end" font-size="12" fill="${th.muted}">${escXml(formatNum(log ? 10 ** t : t, 3))}</text>`);
  }
  for (const t of xt.ticks) {
    parts.push(`<text x="${sx(t).toFixed(1)}" y="${m.t + ph + 20}" text-anchor="middle" font-size="12" fill="${th.muted}">${escXml(formatCompact(t))}</text>`);
  }
  parts.push(`<line x1="${m.l}" x2="${m.l + pw}" y1="${m.t + ph}" y2="${m.t + ph}" stroke="${th.muted}"/>`);
  parts.push(`<text x="${m.l + pw / 2}" y="${m.t + ph + 42}" text-anchor="middle" font-size="13" fill="${th.muted}">${escXml(xLabel)}</text>`);
  const pathOf = (xs, ys) => {
    let d = "", pen = false;
    xs.forEach((x, i) => {
      const y = fy(ys[i]);
      if (y == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${sx(x).toFixed(2)},${sy(y).toFixed(2)}`;
      pen = true;
    });
    return d;
  };
  if (band) {
    const up = band.xs.map((x, i) => [x, fy(band.hi[i])]).filter((p) => p[1] != null);
    const dn = band.xs.map((x, i) => [x, fy(band.lo[i])]).filter((p) => p[1] != null).reverse();
    if (up.length && dn.length) {
      const d = [...up, ...dn].map(([x, y]) => `${sx(x).toFixed(2)},${sy(y).toFixed(2)}`).join("L");
      parts.push(`<path d="M${d}Z" fill="${band.color}" fill-opacity="0.18" stroke="none"/>`);
    }
  }
  for (const s of series) {
    const d = pathOf(s.xs, s.ys);
    if (!d) continue;
    const dash = s.dash ? ` stroke-dasharray="${s.dash.join(" ")}"` : "";
    parts.push(`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width ?? 2}" stroke-opacity="${s.opacity ?? 1}"${dash} stroke-linejoin="round" stroke-linecap="round"/>`);
  }
  series.forEach((s, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = m.l + col * (pw / 3), y = m.t + ph + 64 + row * 20;
    const label = s.label.length > 48 ? s.label.slice(0, 47) + "…" : s.label;
    parts.push(`<rect x="${x}" y="${y - 9}" width="14" height="4" rx="2" fill="${s.color}" fill-opacity="${s.opacity ?? 1}"/>`);
    parts.push(`<text x="${x + 20}" y="${y - 3}" font-size="12" fill="${th.text}">${escXml(label)}</text>`);
  });
  parts.push("</svg>");
  return parts.join("");
}
