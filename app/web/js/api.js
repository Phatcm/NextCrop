// Thin client for app/api. Same origin by default; use ?api=http://localhost:8000 (or window.FIELD_SHIFT_API) in dev.

const BASE = String(window.FIELD_SHIFT_API ?? new URLSearchParams(location.search).get("api") ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}

async function get(path, params = {}, signal) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    (Array.isArray(v) ? v : [v]).forEach((x) => qs.append(k, x));
  }
  let res;
  try {
    res = await fetch(`${BASE}${path}${qs.size ? "?" + qs : ""}`, { signal });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError(0, "network", "Không kết nối được máy chủ.");
  }
  const body = await res.json().catch(() => null);
  if (res.ok) return body;
  const d = body?.detail;
  if (d && typeof d === "object" && !Array.isArray(d)) throw new ApiError(res.status, d.code ?? "error", d.message ?? "Lỗi không rõ.");
  throw new ApiError(res.status, "invalid", "Tham số không hợp lệ.");
}

export const crops = (lang, signal) => get("/api/crops", { lang }, signal).then((b) => b.crops);
export const options = (p, signal) => get("/api/options", p, signal);
export const cells = (p, signal) => get("/api/cells", p, signal);
export const nasa = (p, signal) => get("/api/nasa", p, signal);
export const health = (signal) => get("/api/health", {}, signal);
