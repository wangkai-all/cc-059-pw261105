/**
 * Small typed wrapper around the backend API. All responses are JSON; errors
 * carry the server's `detail` message so the UI can show something useful.
 */
const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep the status text */
    }
    throw new Error(message);
  }
  if (res.status === 204) return null;
  return res.json();
}

const post = (path, body) =>
  request(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request("/health"),
  taxonomy: () => request("/taxonomy"),
  pending: () => request("/references/pending"),
  graph: (filters) => post("/graph", filters),
  edge: (source, target) => request(`/edges/${encodeURIComponent(source)}/${encodeURIComponent(target)}`),
  link: (refId, targetPaperId) =>
    post(`/references/${refId}/link`, { target_paper_id: targetPaperId }),
  unlink: (refId) => post(`/references/${refId}/unlink`),
  searchCandidates: (refId, q) =>
    request(`/references/search?ref_id=${refId}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  importFile: (kind, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/import/${kind}`, { method: "POST", body: form });
  },
  importSample: () => post("/import/sample"),
  reset: () => post("/reset"),
  rebuild: () => post("/edges/rebuild"),
  listSnapshots: () => request("/snapshots"),
  getSnapshot: (id) => request(`/snapshots/${id}`),
  saveSnapshot: (name, filters) => post("/snapshots", { name, filters }),
  deleteSnapshot: (id) => request(`/snapshots/${id}`, { method: "DELETE" }),
};
