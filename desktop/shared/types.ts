// Types for the bot's HTTP API (the contract the api/ thread implements) and the
// IPC bridge between Electron's main process and the renderer.
// Field names follow the SQLite columns in state_manager.py (snake_case), since the
// API serves those rows. Fields not guaranteed by the contract are optional.

export type Mode = "paper" | "live";

export interface BotStatus {
  mode: Mode;
  exchange: string;
  symbols: string[];
  timeframe: string;
  running: boolean;
  today_pnl: number;
  /** true when the daily loss limit stops new entries until UTC midnight */
  entries_halted: boolean;
  equity?: number;
  last_candle_at?: string | null;
  server_time?: string;
}

export interface Position {
  id: number;
  symbol: string;
  side: "long" | "short";
  quantity: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number | null;
  initial_stop?: number;
  /** current trailing stop level; null when trailing has not activated */
  trailing_stop?: number | null;
  last_price?: number | null;
  unrealized_pnl: number | null;
  opened_at: string;
  mode?: Mode;
  /** true when a close command is already queued for this position */
  close_pending?: boolean;
}

export interface Trade {
  id: number;
  position_id: number | null;
  symbol: string;
  side: string;
  action: string;
  quantity: number;
  price: number;
  fee: number;
  pnl: number | null;
  reason: string | null;
  mode: Mode;
  timestamp: string;
}

/** Mirrors performance.compute_performance. profit_factor may be null for infinity. */
export interface PnlSummary {
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number | null;
  expectancy: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  fees: number;
}

/** [timestamp_ms, open, high, low, close, volume], as ccxt returns OHLCV. */
export type Candle = [number, number, number, number, number, number];

export type SettingValue = number | string | boolean;

export interface Setting {
  key: string;
  value: SettingValue;
  description: string;
  updated_at: string;
}

export interface LogLine {
  id: number;
  timestamp: string;
  level: string;
  category: string;
  symbol: string | null;
  message: string;
}

export interface CloseResult {
  command_id: number;
  status: string;
}

export type WsEvent =
  | { type: "status"; data: BotStatus }
  | { type: "positions"; data: Position[] }
  | { type: "log"; data: LogLine };

// ---------------------------------------------------------------- IPC bridge

export interface ConnectionConfig {
  baseUrl: string;
  /** Only whether a token is stored crosses into the renderer, never the token itself. */
  hasToken: boolean;
}

export interface ConnectionInput {
  baseUrl: string;
  /** undefined keeps the stored token */
  token?: string;
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; error: string };

export type WsState = "connecting" | "open" | "closed";

/** Read-only calls plus the only two writes the app may make. */
export type ApiCall =
  | { kind: "status" }
  | { kind: "positions" }
  | { kind: "trades"; limit: number }
  | { kind: "pnl" }
  | { kind: "candles"; symbol: string; timeframe: string; limit: number }
  | { kind: "settings" }
  | { kind: "logs"; limit: number }
  | { kind: "closePosition"; id: number }
  | { kind: "updateSetting"; key: string; value: SettingValue };

export interface DesktopBridge {
  getConfig(): Promise<ConnectionConfig>;
  saveConfig(input: ConnectionInput): Promise<ConnectionConfig>;
  call<T>(call: ApiCall): Promise<ApiResult<T>>;
  getWsState(): Promise<WsState>;
  onEvent(listener: (event: WsEvent) => void): () => void;
  onWsState(listener: (state: WsState) => void): () => void;
}
