import { connect } from "./live.js";
import { renderHome } from "./pages/home.js";
import { h, icon } from "./ui.js";

const root = document.getElementById("app");
const pages = { run: null, compare: null }; // Görev 12/13 bu sayfaları ekler
let cleanup = null;
let token = 0;

export function registerPage(name, render) {
  pages[name] = render;
}

async function route() {
  const current = ++token;
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  const [path, query = ""] = (location.hash.slice(1) || "/").split("?");
  const params = new URLSearchParams(query);
  const parts = path.split("/").filter(Boolean);
  const section = parts[0] === "compare" ? "compare" : parts[0] === "run" ? "run" : "home";
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === section));
  const view = h("div", { class: "view" });
  root.replaceChildren(view);
  let dispose;
  if (section === "run" && pages.run) dispose = await pages.run(view, Number(parts[1]), params);
  else if (section === "compare" && pages.compare) dispose = await pages.compare(view, params);
  else dispose = renderHome(view);
  if (current !== token) { dispose?.(); return; }
  cleanup = dispose;
  root.focus({ preventScroll: true });
}

function initTheme() {
  const button = document.getElementById("theme-toggle");
  const paint = () => {
    const dark = document.documentElement.dataset.theme !== "light";
    button.replaceChildren(icon(dark ? "sun" : "moon", 18));
    button.setAttribute("aria-label", dark ? "Açık temaya geç" : "Koyu temaya geç");
    button.title = button.getAttribute("aria-label");
  };
  button.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("rlpanel-theme", next); } catch { /* depolama kapalı */ }
    paint();
    window.dispatchEvent(new Event("rlpanel-theme"));
  });
  paint();
}

export function start() {
  window.addEventListener("hashchange", route);
  initTheme();
  connect();
  route();
}
