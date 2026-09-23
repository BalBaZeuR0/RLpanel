async function request(method, url, body, isForm = false) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) options.body = body;
    else { options.body = JSON.stringify(body); options.headers["Content-Type"] = "application/json"; }
  }
  const res = await fetch(url, options);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : detail?.message || `HTTP ${res.status}`;
    const err = new Error(message);
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return data;
}

const q = encodeURIComponent;

export const api = {
  runs: (project) => request("GET", "/api/runs" + (project ? `?project=${q(project)}` : "")),
  run: (id) => request("GET", `/api/runs/${id}`),
  metrics: (id, keys) => request("GET", `/api/runs/${id}/metrics` + (keys?.length ? `?keys=${q(keys.join(","))}` : "")),
  logs: (id, { after = 0, tail } = {}) => request("GET", `/api/runs/${id}/logs?after=${after}` + (tail ? `&tail=${tail}` : "")),
  deleteRun: (id) => request("DELETE", `/api/runs/${id}`),
  upload: (file, project, run) => {
    const form = new FormData();
    form.append("file", file);
    form.append("project", project);
    form.append("run", run);
    return request("POST", "/api/upload", form, true);
  },
  watchList: () => request("GET", "/api/watch"),
  watchAdd: (path) => request("POST", "/api/watch", { path }),
  watchRemove: (path) => request("DELETE", `/api/watch?path=${q(path)}`),
  exportZip: async (id) => {
    const res = await fetch(`/api/runs/${id}/export.zip`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.blob();
  },
};
