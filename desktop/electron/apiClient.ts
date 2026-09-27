import type { ApiCall, ApiResult } from "../shared/types";
import { buildRequest } from "./apiRoutes";

const TIMEOUT_MS = 10_000;

/** Performs one allowed API call. Runs in the main process so the token never
 * reaches the renderer and the API server needs no CORS setup. */
export async function performCall<T>(baseUrl: string, token: string, call: ApiCall): Promise<ApiResult<T>> {
  let req;
  try {
    req = buildRequest(call);
  } catch (err) {
    return { ok: false, status: 0, error: (err as Error).message };
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${baseUrl}${req.path}`, {
      method: req.method,
      headers: {
        Accept: "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(req.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: req.body !== undefined ? JSON.stringify(req.body) : undefined,
      signal: controller.signal,
    });
    const text = await res.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = text;
    }
    if (!res.ok) {
      const detail =
        body && typeof body === "object" && "detail" in body ? String((body as { detail: unknown }).detail) : text;
      // The API's messages are Turkish; the status code is only shown when there is no message.
      const error = res.status === 401 || res.status === 403 ? "Token geçersiz veya eksik" : detail || `HTTP ${res.status}`;
      return { ok: false, status: res.status, error };
    }
    return { ok: true, data: body as T };
  } catch (err) {
    const e = err as Error;
    const msg = e.name === "AbortError" ? "Bot yanıt vermedi (zaman aşımı)" : "Bota bağlanılamadı; bot kapalı olabilir";
    return { ok: false, status: 0, error: msg };
  } finally {
    clearTimeout(timer);
  }
}
