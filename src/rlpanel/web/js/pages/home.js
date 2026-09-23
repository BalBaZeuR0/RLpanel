import { api } from "../api.js";
import { REWARD_KEYS, formatCompact, formatNum, pickKey, progressInfo } from "../core.js";
import { onEvent } from "../live.js";
import { SOURCE, STATUS, confirmDelete, field, fmtDate, h, icon, modal, sparkline, statusBadge, toast } from "../ui.js";

const SNIPPET = `from rlpanel import Panel, PanelCallback

panel = Panel(project="Projem", run="seed0", config=cfg)
model.learn(total_timesteps=100_000, callback=PanelCallback(panel))
panel.finish()`;

export function renderHome(view) {
  const state = { runs: new Map(), selected: new Set(), filters: { q: "", project: "", status: "", host: "", days: "" }, loaded: false };
  let drawTimer = null;

  const listEl = h("div", { class: "run-groups", "aria-live": "polite" });
  const compareLabel = h("span", {}, "Karşılaştır");
  const compareBtn = h("button", { class: "btn btn-primary", type: "button", disabled: true,
    onclick: () => { location.hash = `#/compare?ids=${[...state.selected].join(",")}`; } }, icon("chart"), compareLabel);
  const projectSel = h("select", { "aria-label": "Proje filtresi", onchange: (e) => { state.filters.project = e.target.value; draw(); } });
  const hostSel = h("select", { "aria-label": "Makine filtresi", onchange: (e) => { state.filters.host = e.target.value; draw(); } });
  const statusSel = h("select", { "aria-label": "Durum filtresi", onchange: (e) => { state.filters.status = e.target.value; draw(); } },
    h("option", { value: "" }, "Tüm durumlar"), Object.entries(STATUS).map(([v, label]) => h("option", { value: v }, label)));
  const dateSel = h("select", { "aria-label": "Tarih filtresi", onchange: (e) => { state.filters.days = e.target.value; draw(); } },
    [["", "Tüm zamanlar"], ["1", "Son 24 saat"], ["7", "Son 7 gün"], ["30", "Son 30 gün"]].map(([v, label]) => h("option", { value: v }, label)));
  const search = h("input", { type: "search", placeholder: "Run ya da proje ara…", "aria-label": "Run ara",
    oninput: (e) => { state.filters.q = e.target.value.toLowerCase(); draw(); } });

  view.replaceChildren(
    h("section", { class: "page-head" },
      h("div", {}, h("h1", {}, "Eğitimler"), h("p", { class: "sub" }, "Canlı ve geçmiş RL eğitimlerin")),
      h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", onclick: openWatch }, icon("folder"), "Klasör izle"),
        h("button", { class: "btn", type: "button", onclick: openUpload }, icon("upload"), "Log yükle"),
        compareBtn)),
    h("div", { class: "toolbar" }, h("label", { class: "search" }, icon("search"), search), projectSel, statusSel, dateSel, hostSel),
    listEl);

  async function load() {
    try {
      const runs = await api.runs();
      state.runs = new Map(runs.map((r) => [r.id, r]));
      state.loaded = true;
      draw();
    } catch (e) {
      listEl.replaceChildren(h("div", { class: "empty" }, h("h2", {}, "Panel sunucusuna ulaşılamadı"), h("p", {}, e.message)));
    }
  }

  function scheduleDraw() {
    if (drawTimer) return;
    drawTimer = setTimeout(() => { drawTimer = null; draw(); }, 200);
  }

  function refillSelect(select, values, allLabel) {
    const current = select.value;
    select.replaceChildren(h("option", { value: "" }, allLabel), values.map((v) => h("option", { value: v }, v)));
    select.value = values.includes(current) ? current : "";
  }

  function draw() {
    const runs = [...state.runs.values()];
    refillSelect(projectSel, [...new Set(runs.map((r) => r.project))].sort(), "Tüm projeler");
    refillSelect(hostSel, [...new Set(runs.map((r) => r.host).filter(Boolean))].sort(), "Tüm makineler");
    for (const id of [...state.selected]) if (!state.runs.has(id)) state.selected.delete(id);
    compareBtn.disabled = state.selected.size < 2;
    compareLabel.textContent = state.selected.size ? `Karşılaştır (${state.selected.size})` : "Karşılaştır";

    if (!state.loaded) return;
    if (!runs.length) {
      listEl.replaceChildren(h("div", { class: "empty" },
        h("h2", {}, "Henüz eğitim yok"),
        h("p", {}, "Eğitim koduna iki satır ekle; eğitim başlayınca burada canlı görünür. Bitmiş bir eğitimi görmek için “Log yükle”yi kullan."),
        h("pre", {}, SNIPPET)));
      return;
    }
    const f = state.filters;
    const since = f.days ? Date.now() / 1000 - Number(f.days) * 86400 : null;
    const visible = runs.filter((r) =>
      (!f.project || r.project === f.project) && (!f.status || r.status === f.status) && (!f.host || r.host === f.host) && (since == null || r.started_at >= since) &&
      (!f.q || `${r.project} ${r.name}`.toLowerCase().includes(f.q)));
    if (!visible.length) {
      listEl.replaceChildren(h("div", { class: "empty small" }, "Filtreyle eşleşen run yok."));
      return;
    }
    const byProject = new Map();
    for (const r of visible.sort((a, b) => b.started_at - a.started_at)) {
      if (!byProject.has(r.project)) byProject.set(r.project, []);
      byProject.get(r.project).push(r);
    }
    listEl.replaceChildren(...[...byProject.keys()].sort((a, b) => a.localeCompare(b, "tr")).map((project) =>
      h("section", { class: "run-group" },
        h("h2", {}, project, h("span", { class: "count" }, byProject.get(project).length)),
        h("div", { class: "run-grid" }, byProject.get(project).map(card)))));
  }

  function card(run) {
    const p = progressInfo(run);
    const selected = state.selected.has(run.id);
    return h("article", { class: `run-card${selected ? " selected" : ""}`, dataset: { id: run.id } },
      h("div", { class: "run-card-top" },
        h("label", { class: "check", title: "Karşılaştırmaya ekle" },
          h("input", { type: "checkbox", checked: selected, "aria-label": `${run.name} karşılaştırmaya ekle`,
            onchange: (e) => { if (e.target.checked) state.selected.add(run.id); else state.selected.delete(run.id); draw(); } })),
        h("a", { class: "run-name", href: `#/run/${run.id}`, title: run.name }, run.name),
        statusBadge(run.status),
        h("button", { class: "icon-btn danger", type: "button", "aria-label": `${run.name} sil`, title: "Sil",
          onclick: () => confirmDelete(run) }, icon("trash"))),
      h("div", { class: "run-meta" },
        [run.host, run.seed != null ? `seed ${run.seed}` : null, fmtDate(run.started_at), SOURCE[run.source]].filter(Boolean).join(" · ")),
      h("div", { class: "run-card-body" },
        h("div", { class: "metric-big" }, h("span", { class: "label" }, "Son reward"), h("span", { class: "value mono" }, formatNum(run.last_reward))),
        sparkline(run.spark || [], { color: run.status === "running" ? "var(--accent)" : "var(--info)" })),
      h("div", { class: "progress" },
        h("div", { class: "progress-track", role: "progressbar", "aria-label": "İlerleme", "aria-valuemin": "0", "aria-valuemax": "100",
          "aria-valuenow": p.pct != null ? String(Math.round(p.pct)) : null },
          h("div", { class: "progress-fill", style: `width:${p.pct ?? 0}%` })),
        h("span", { class: "progress-text mono" },
          p.pct != null ? `%${p.pct.toFixed(0)} · ${formatCompact(p.cur)}/${formatCompact(p.total)}` : `${formatCompact(p.cur)} adım`)));
  }

  function projects() {
    return [...new Set([...state.runs.values()].map((r) => r.project))].sort();
  }

  function openUpload() {
    let file = null;
    const project = h("input", { id: "up-project", placeholder: "Yüklenenler", list: "up-projects", autocomplete: "off" });
    const runName = h("input", { id: "up-run", placeholder: "Run adı", autocomplete: "off" });
    const fileLabel = h("span", { class: "drop-file" }, "Dosya seçilmedi");
    const input = h("input", { type: "file", id: "up-file", class: "sr-only", onchange: (e) => pick(e.target.files[0]) });
    const drop = h("label", { class: "dropzone", for: "up-file",
      ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); },
      ondragleave: () => drop.classList.remove("over"),
      ondrop: (e) => { e.preventDefault(); drop.classList.remove("over"); pick(e.dataTransfer.files[0]); } },
      icon("upload", 22), h("strong", {}, "Dosyayı buraya bırak ya da tıklayıp seç"),
      h("span", {}, "progress.csv · tfevents · results.json · .rlpanel_buffer.jsonl · .zip"), fileLabel, input);
    const result = h("div", { "aria-live": "polite" });
    const submit = h("button", { class: "btn btn-primary", type: "button", disabled: true, onclick: send }, "Yükle");

    function pick(f) {
      if (!f) return;
      file = f;
      fileLabel.textContent = `${f.name} · ${(f.size / 1024).toFixed(1)} KB`;
      if (!runName.value) runName.value = suggestRunName(f.name);
      submit.disabled = false;
    }

    async function send() {
      submit.disabled = true;
      result.replaceChildren(h("p", { class: "muted small" }, "Yükleniyor…"));
      try {
        const r = await api.upload(file, project.value.trim(), runName.value.trim());
        m.close();
        toast(`${r.metrics} metrik satırı içe alındı`, "success");
        if (r.errors.length) toast(`${r.errors.length} uyarı: ${r.errors[0]}`, "warn", 8000);
        location.hash = `#/run/${r.id}`;
      } catch (err) {
        const items = [h("p", { class: "error" }, err.message)];
        if (err.status === 409 && err.detail?.run_id) {
          items.push(h("a", { href: `#/run/${err.detail.run_id}`, onclick: () => m.close() }, "Mevcut run'ı aç"));
        }
        for (const line of err.detail?.errors || []) items.push(h("div", { class: "muted small" }, line));
        result.replaceChildren(...items);
        submit.disabled = false;
      }
    }

    const m = modal({
      title: "Log yükle",
      body: h("div", { class: "form" }, drop, field("Proje", project),
        h("datalist", { id: "up-projects" }, projects().map((p) => h("option", { value: p }))),
        field("Run adı", runName), result),
      actions: [h("button", { class: "btn btn-ghost", type: "button", onclick: () => m.close() }, "Vazgeç"), submit],
    });
  }

  async function openWatch() {
    const list = h("ul", { class: "watch-list" });
    const input = h("input", { placeholder: "D:\\Projects\\Deney\\runs", "aria-label": "Klasör yolu" });
    const error = h("p", { class: "error", "aria-live": "polite" });
    const drawList = (roots) => list.replaceChildren(...(roots.length
      ? roots.map((root) => h("li", {}, h("code", { title: root }, root),
          h("button", { class: "icon-btn danger", type: "button", "aria-label": `${root} izlemeyi bırak`,
            onclick: async () => { try { drawList((await api.watchRemove(root)).roots); } catch (e) { error.textContent = e.message; } } }, icon("x"))))
      : [h("li", { class: "muted" }, "Henüz izlenen klasör yok")]));
    const add = async () => {
      error.textContent = "";
      try {
        const r = await api.watchAdd(input.value.trim());
        input.value = "";
        drawList(r.roots);
        toast("Klasör izleniyor", "success");
      } catch (e) { error.textContent = e.message; }
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    modal({
      title: "Klasör izle",
      body: h("div", { class: "form" },
        h("p", { class: "muted small" }, "Klasördeki her progress.csv / tfevents / results.json bir run olur: run adı dosyanın klasörü, proje onun üst klasörü. Dosyalar büyüdükçe grafikler canlı güncellenir."),
        h("div", { class: "row" }, input, h("button", { class: "btn btn-primary", type: "button", onclick: add }, icon("plus"), "Ekle")),
        error, list),
    });
    try { drawList((await api.watchList()).roots); } catch (e) { error.textContent = e.message; }
  }

  const off = onEvent((ev) => {
    if (ev.type === "run" && ev.run) {
      state.runs.set(ev.run.id, { ...(state.runs.get(ev.run.id) || {}), ...ev.run });
      scheduleDraw();
    } else if (ev.type === "batch" && ev.run) {
      const current = state.runs.get(ev.run.id);
      if (!current || ev.reset) { load(); return; }
      Object.assign(current, ev.run);
      const key = current.reward_key || pickKey(ev.metrics.map((m) => m[0]), REWARD_KEYS);
      if (key) {
        current.reward_key = key;
        for (const [k, , value] of ev.metrics) {
          if (k !== key) continue;
          current.last_reward = value;
          (current.spark ||= []).push(value);
          if (current.spark.length > 60) current.spark.shift();
        }
      }
      scheduleDraw();
    } else if (ev.type === "deleted") {
      state.runs.delete(ev.run_id);
      scheduleDraw();
    } else if (ev.type === "reconnected") {
      load();
    }
  });

  load();
  return () => { off(); clearTimeout(drawTimer); };
}

function suggestRunName(filename) {
  const stem = filename.replace(/\.[^.]+$/, "");
  if (/^(progress|results|metrics|config|console|run)$/i.test(stem) || /tfevents|rlpanel_buffer/i.test(filename)) {
    return `yukleme-${new Date().toISOString().slice(0, 16).replace("T", "-")}`;
  }
  return stem;
}
