const listeners = new Set();
let retry = 500;
let everOpened = false;

export function onEvent(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit(event) {
  for (const fn of [...listeners]) {
    try { fn(event); } catch (err) { console.error(err); }
  }
}

function setState(state) {
  const el = document.getElementById("conn");
  if (!el) return;
  el.dataset.state = state;
  el.querySelector(".conn-label").textContent = { open: "Canlı", connecting: "Bağlanıyor", closed: "Bağlantı yok" }[state];
}

export function connect() {
  setState("connecting");
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => {
    retry = 500;
    setState("open");
    if (everOpened) emit({ type: "reconnected" });
    everOpened = true;
  };
  ws.onmessage = (e) => {
    let event;
    try { event = JSON.parse(e.data); } catch { return; }
    emit(event);
  };
  ws.onclose = () => {
    setState("closed");
    setTimeout(connect, retry);
    retry = Math.min(retry * 2, 10_000);
  };
}
