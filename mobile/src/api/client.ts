import type {
  Candle,
  CloseResult,
  Command,
  LogEvent,
  Pnl,
  Position,
  Setting,
  SettingValue,
  Status,
  Trade,
} from './types';

export interface Connection {
  baseUrl: string; // e.g. http://192.168.1.20:8000
  token: string;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const TIMEOUT_MS = 10_000;

export function normalizeBaseUrl(url: string): string {
  let u = url.trim().replace(/\/+$/, '');
  if (u && !/^https?:\/\//i.test(u)) u = `http://${u}`;
  return u;
}

async function request<T>(conn: Connection, path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let resp: Response;
  try {
    resp = await fetch(`${conn.baseUrl}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${conn.token}`,
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch (e) {
    throw new ApiError(0, controller.signal.aborted ? 'Sunucu yanıt vermedi (zaman aşımı)' : 'Sunucuya ulaşılamadı');
  } finally {
    clearTimeout(timer);
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      // not JSON
    }
    if (resp.status === 401) detail = 'Token geçersiz';
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

export const api = {
  status: (c: Connection) => request<Status>(c, '/api/status'),
  positions: (c: Connection) => request<{ positions: Position[] }>(c, '/api/positions').then((r) => r.positions),
  closePosition: (c: Connection, id: number) =>
    request<CloseResult>(c, `/api/positions/${id}/close`, { method: 'POST' }),
  command: (c: Connection, id: number) => request<Command>(c, `/api/commands/${id}`),
  trades: (c: Connection, limit = 100) =>
    request<{ trades: Trade[] }>(c, `/api/trades?limit=${limit}`).then((r) => r.trades),
  pnl: (c: Connection) => request<Pnl>(c, '/api/pnl'),
  candles: (c: Connection, symbol: string, timeframe?: string, limit = 120) => {
    const q = new URLSearchParams({ symbol, limit: String(limit) });
    if (timeframe) q.set('timeframe', timeframe);
    return request<{ candles: Candle[] }>(c, `/api/candles?${q.toString()}`).then((r) => r.candles);
  },
  settings: (c: Connection) => request<{ settings: Setting[] }>(c, '/api/settings').then((r) => r.settings),
  updateSetting: (c: Connection, key: string, value: SettingValue) =>
    request<{ key: string; value: SettingValue }>(c, `/api/settings/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),
  logs: (c: Connection, limit = 200, category?: string) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (category) q.set('category', category);
    return request<{ logs: LogEvent[] }>(c, `/api/logs?${q.toString()}`).then((r) => r.logs);
  },
};

export function wsUrl(conn: Connection): string {
  const base = conn.baseUrl.replace(/^http/i, 'ws');
  return `${base}/api/ws?token=${encodeURIComponent(conn.token)}`;
}
