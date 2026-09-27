import type { ApiCall } from "../shared/types";

export interface HttpRequest {
  method: "GET" | "POST" | "PUT";
  path: string;
  body?: unknown;
}

// Setting keys the app refuses to write even if the server exposes them: switching
// paper/live must stay a deliberate step on the bot's host, never a click here.
const FORBIDDEN_SETTING = /(^|_)(mode|paper|live|api_key|secret)(_|$)/i;
const SETTING_KEY = /^[a-z0-9_]{1,64}$/;
const SYMBOL = /^[A-Za-z0-9._:/-]{1,40}$/;
const TIMEFRAME = /^[0-9]{1,3}[smhdwM]$/;

function clampLimit(limit: number, max: number): number {
  if (!Number.isFinite(limit)) return 100;
  return Math.min(max, Math.max(1, Math.floor(limit)));
}

/** Maps an allowed call to its HTTP request. Anything else throws, so the renderer
 * can never reach an endpoint outside this list (e.g. to place an order). */
export function buildRequest(call: ApiCall): HttpRequest {
  switch (call.kind) {
    case "status":
      return { method: "GET", path: "/api/status" };
    case "positions":
      return { method: "GET", path: "/api/positions" };
    case "trades":
      return { method: "GET", path: `/api/trades?limit=${clampLimit(call.limit, 1000)}` };
    case "pnl":
      return { method: "GET", path: "/api/pnl" };
    case "candles": {
      if (!SYMBOL.test(call.symbol)) throw new Error(`Geçersiz sembol: ${call.symbol}`);
      if (!TIMEFRAME.test(call.timeframe)) throw new Error(`Geçersiz zaman dilimi: ${call.timeframe}`);
      const q = new URLSearchParams({
        symbol: call.symbol,
        timeframe: call.timeframe,
        limit: String(clampLimit(call.limit, 1000)),
      });
      return { method: "GET", path: `/api/candles?${q.toString()}` };
    }
    case "settings":
      return { method: "GET", path: "/api/settings" };
    case "logs":
      return { method: "GET", path: `/api/logs?limit=${clampLimit(call.limit, 2000)}` };
    case "closePosition":
      if (!Number.isInteger(call.id) || call.id <= 0) throw new Error(`Geçersiz pozisyon id: ${call.id}`);
      return { method: "POST", path: `/api/positions/${call.id}/close` };
    case "updateSetting": {
      if (!SETTING_KEY.test(call.key)) throw new Error(`Geçersiz ayar anahtarı: ${call.key}`);
      if (FORBIDDEN_SETTING.test(call.key)) throw new Error(`Bu ayar uygulamadan değiştirilemez: ${call.key}`);
      const t = typeof call.value;
      if (t !== "number" && t !== "string" && t !== "boolean") throw new Error("Geçersiz ayar değeri");
      return { method: "PUT", path: `/api/settings/${call.key}`, body: { value: call.value } };
    }
    default: {
      const never: never = call;
      throw new Error(`İzin verilmeyen çağrı: ${JSON.stringify(never)}`);
    }
  }
}

/** Normalises a user-entered base URL ("127.0.0.1:8000/" -> "http://127.0.0.1:8000"). */
export function normaliseBaseUrl(input: string): string {
  let url = input.trim();
  if (!/^https?:\/\//i.test(url)) url = `http://${url}`;
  const parsed = new URL(url);
  parsed.pathname = parsed.pathname.replace(/\/+$/, "").replace(/\/api$/, "");
  parsed.search = "";
  parsed.hash = "";
  return parsed.toString().replace(/\/+$/, "");
}

export function wsUrl(baseUrl: string, token: string): string {
  const u = new URL(`${baseUrl}/api/ws`);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  u.searchParams.set("token", token);
  return u.toString();
}
