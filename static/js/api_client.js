// =================API 客户端=================
const buildUrl = (path, query = {}) => {
  const qs = new URLSearchParams(query || {}).toString();
  return `${path}${qs ? `?${qs}` : ""}`;
};

const parseErrorMessage = (payload, status) => {
  const error = payload?.error;
  if (!error) return `HTTP ${status}`;
  if (typeof error?.message === "string" && error.message.trim()) return error.message;
  return `HTTP ${status}`;
};

export const api = {
  async req(method, path, { body = null, query = null, headers = null } = {}) {
    const url = buildUrl(path, query || {});
    const baseHeaders = {};
    if (!(body instanceof FormData)) {
      baseHeaders["Content-Type"] = "application/json";
    }
    const res = await fetch(url, {
      method,
      headers: { ...baseHeaders, ...(headers || {}) },
      body: body == null ? null : (body instanceof FormData ? body : JSON.stringify(body))
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload?.error) {
      throw new Error(parseErrorMessage(payload, res.status));
    }
    return payload.data;
  },
  get(path, query = null) {
    return this.req("GET", path, { query });
  },
  post(path, body = null, query = null) {
    return this.req("POST", path, { body, query });
  },
  put(path, body = null, query = null) {
    return this.req("PUT", path, { body, query });
  },
  del(path, query = null) {
    return this.req("DELETE", path, { query });
  },
  upload(path, files, query = null) {
    const form = new FormData();
    Array.from(files || []).forEach((file) => form.append("files", file));
    return this.req("POST", path, { body: form, query });
  }
};

