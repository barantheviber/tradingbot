import type {
  ApiCall, BotStatus, Candle, CloseResult, LogLine, PnlSummary, Position, Setting, SettingValue, Trade,
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
  status: () => call<BotStatus>({ kind: "status" }),
  positions: () => call<Position[]>({ kind: "positions" }),
  trades: (limit = 200) => call<Trade[]>({ kind: "trades", limit }),
  pnl: () => call<PnlSummary>({ kind: "pnl" }),
  candles: (symbol: string, timeframe: string, limit = 300) =>
    call<Candle[]>({ kind: "candles", symbol, timeframe, limit }),
  settings: () => call<Setting[]>({ kind: "settings" }),
  logs: (limit = 300) => call<LogLine[]>({ kind: "logs", limit }),
  closePosition: (id: number) => call<CloseResult>({ kind: "closePosition", id }),
  updateSetting: (key: string, value: SettingValue) => call<Setting>({ kind: "updateSetting", key, value }),
};
