import type {
  ApiCall, Candle, CloseResult, Command, LogEvent, Pnl, Position, Setting, SettingValue, Status, Trade,
} from "../shared/types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function call<T>(c: ApiCall): Promise<T> {
  const res = await window.desktop.call<T>(c);
  if (!res.ok) throw new ApiError(res.error, res.status);
  return res.data;
}

// Every call the app can make. There is deliberately no way to open orders or change paper/live mode.
export const api = {
  status: () => call<Status>({ kind: "status" }),
  positions: () => call<{ positions: Position[] }>({ kind: "positions" }).then((r) => r.positions),
  command: (id: number) => call<Command>({ kind: "command", id }),
  trades: (limit = 200) => call<{ trades: Trade[] }>({ kind: "trades", limit }).then((r) => r.trades),
  pnl: () => call<Pnl>({ kind: "pnl" }),
  candles: (symbol: string, timeframe: string, limit = 300) =>
    call<{ candles: Candle[] }>({ kind: "candles", symbol, timeframe, limit }).then((r) => r.candles),
  settings: () => call<{ settings: Setting[] }>({ kind: "settings" }).then((r) => r.settings),
  /** Oldest first (the API sends newest first). */
  logs: (limit = 300) => call<{ logs: LogEvent[] }>({ kind: "logs", limit }).then((r) => r.logs.slice().reverse()),
  closePosition: (id: number) => call<CloseResult>({ kind: "closePosition", id }),
  updateSetting: (key: string, value: SettingValue) =>
    call<{ key: string; value: SettingValue }>({ kind: "updateSetting", key, value }),
};
