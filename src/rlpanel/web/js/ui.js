import { ICONS } from "./icons.js";
import { api } from "./api.js";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "value" || k === "disabled") el[k] = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function icon(name, size = 16) {
  const span = document.createElement("span");
  span.className = "icon";
  span.setAttribute("aria-hidden", "true");
  span.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
  return span;
}

export function toast(message, kind = "info", ms = 4000) {
  const root = document.getElementById("toast-root");
  const el = h("div", { class: `toast toast-${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  root.append(el);
  setTimeout(() => { el.classList.add("leaving"); setTimeout(() => el.remove(), 200); }, ms);
}

export function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const STATUS = {
  running: "Canlı", finished: "Bitti", crashed: "Çöktü", stopped: "Durduruldu", unresponsive: "Yanıt vermiyor",
};
export const SOURCE = { client: "canlı istemci", watch: "klasör izleme", upload: "yükleme" };

export function statusBadge(status) {
  return h("span", { class: `badge badge-${STATUS[status] ? status : "stopped"}` },
    h("span", { class: "badge-dot", "aria-hidden": "true" }), STATUS[status] || status);
}

export function fmtDate(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("tr-TR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function field(label, input) {
  return h("label", { class: "field" }, h("span", {}, label), input);
}

export function modal({ title, body, actions = [], onClose }) {
  const previous = document.activeElement;
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() {
    overlay.remove();
    document.removeEventListener("keydown", onKey);
    previous?.focus?.();
    onClose?.();
  }
  const dialog = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "modal-title", tabindex: "-1" },
    h("div", { class: "modal-head" }, h("h2", { id: "modal-title" }, title),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Kapat", onclick: () => close() }, icon("x"))),
    h("div", { class: "modal-body" }, body),
    actions.length ? h("div", { class: "modal-actions" }, actions) : null);
  const overlay = h("div", { class: "overlay", onclick: (e) => { if (e.target === overlay) close(); } }, dialog);
  document.body.append(overlay);
  document.addEventListener("keydown", onKey);
  (dialog.querySelector("input:not([type=file]), .btn-primary, .btn-danger") || dialog).focus();
  return { close, dialog };
}

export function sparkline(values, { width = 120, height = 34, color = "var(--accent)" } = {}) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("spark");
  const vals = (values || []).filter(Number.isFinite);
  if (vals.length >= 2) {
    let min = Infinity, max = -Infinity;
    for (const v of vals) { if (v < min) min = v; if (v > max) max = v; }
    const span = max - min || 1;
    const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`).join(" ");
    const line = document.createElementNS(ns, "polyline");
    line.setAttribute("points", pts);
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", color);
    line.setAttribute("stroke-width", "1.5");
    line.setAttribute("stroke-linejoin", "round");
    svg.append(line);
  }
  return svg;
}

export function confirmDelete(run, onDone) {
  const m = modal({
    title: "Run silinsin mi?",
    body: h("p", {}, `"${run.project} / ${run.name}" ve tüm metrikleri kalıcı olarak silinecek.`),
    actions: [
      h("button", { class: "btn btn-ghost", type: "button", onclick: () => m.close() }, "Vazgeç"),
      h("button", { class: "btn btn-danger", type: "button", onclick: async () => {
        try { await api.deleteRun(run.id); m.close(); toast("Run silindi", "success"); onDone?.(); }
        catch (e) { toast(e.message, "error"); }
      } }, icon("trash"), "Sil"),
    ],
  });
}
