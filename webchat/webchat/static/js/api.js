// API 访问层：票据仅存内存，全部请求经 Authorization 头；URL 永不携带凭据。

let token = "";

export function setToken(value) {
  token = value || "";
}

export function hasToken() {
  return token !== "";
}

export function getToken() {
  return token;
}

function authHeaders(extra = {}) {
  return { Authorization: `Bearer ${token}`, ...extra };
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.detail = detail || "";
  }
}

// 通用 JSON 请求：非 2xx 抛 ApiError（detail 取服务端可读错误）
export async function api(path, { method = "GET", body, headers } = {}) {
  const opts = { method, headers: authHeaders(headers || {}) };
  if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    let detail = "";
    try { detail = (await resp.json()).detail || ""; } catch (_) { /* 忽略 */ }
    throw new ApiError(resp.status, detail);
  }
  return resp.json();
}

// multipart 上传（浏览器自动带 boundary，不手设 Content-Type）
export async function uploadFile(path, channel, file) {
  const form = new FormData();
  form.append("channel", channel);
  form.append("file", file);
  const resp = await fetch(path, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!resp.ok) {
    let detail = "";
    try { detail = (await resp.json()).detail || ""; } catch (_) { /* 忽略 */ }
    throw new ApiError(resp.status, detail);
  }
  return resp.json();
}

// 带凭据头的二进制取回（下载走 blob，不落 URL）
export async function fetchBlob(path, headers = {}) {
  const resp = await fetch(path, { headers: authHeaders(headers) });
  if (!resp.ok) {
    let detail = "";
    try { detail = (await resp.json()).detail || ""; } catch (_) { /* 忽略 */ }
    throw new ApiError(resp.status, detail);
  }
  return resp.blob();
}
