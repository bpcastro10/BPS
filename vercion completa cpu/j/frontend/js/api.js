/**
 * Cliente de la API del backend. Si el frontend se abre desde el propio backend usa el mismo origen;
 * si se abre como archivo suelto, apunta a http://127.0.0.1:8000.
 */
const API_BASE = location.protocol.startsWith("http") ? "" : "http://127.0.0.1:8000";

function newRequestId() {
  if (window.crypto?.randomUUID) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

const Api = {
  async request(path, options = {}) {
    const response = await fetch(API_BASE + path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      let message = `Error ${response.status}`;
      try {
        const body = await response.json();
        message = body.message || (Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join(", ") : body.detail) || message;
      } catch (_) { /* respuesta sin JSON */ }
      throw new Error(message);
    }
    return response.status === 204 ? null : response.json();
  },

  listChecks(params) {
    const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null));
    return this.request(`/v1/checks?${query}`);
  },

  getCheck(id) {
    return this.request(`/v1/checks/${id}`);
  },

  updateCheck(id, changes) {
    return this.request(`/v1/checks/${id}`, { method: "PATCH", body: JSON.stringify(changes) });
  },

  deleteCheck(id) {
    return this.request(`/v1/checks/${id}`, { method: "DELETE" });
  },

  reprocessCheck(id) {
    return this.request(`/v1/checks/${id}/reprocessings`, {
      method: "POST",
      headers: { "Idempotency-Key": newRequestId() },
    });
  },

  scanFolder() {
    return this.request("/v1/scans", { method: "POST", body: JSON.stringify({ request_id: newRequestId() }) });
  },

  summary() {
    return this.request("/v1/summary");
  },

  imageUrl(check) {
    return `${API_BASE}${check.image_url}?v=${encodeURIComponent(check.processed_at)}`;
  },

  excelUrl(params) {
    const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null));
    return `${API_BASE}/v1/exports/excel?${query}`;
  },
};
