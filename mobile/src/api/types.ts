// Shapes returned by the bot's HTTP API (api/server.py). Keep in sync with api/service.py.

export type Mode = 'paper' | 'live';

export interface Status {
  mode: Mode;
  exchange: string;
  market_type: string;
  testnet: boolean;
  symbols: string[];
  timeframe: string;
  bot_running: boolean;
  bot_state: 'running' | 'stopped' | 'unknown' | string;
  heartbeat_age_sec: number | null;
  equity: number | null;
  day_start_equity: number | null;
  today_pnl: number | null;
  daily_loss_pct: number | null;
  daily_loss_limit_pct: number;
  entries_halted_by_daily_limit: boolean;
  trading_enabled: boolean;
  open_positions: number;
  max_open_positions: number | null;
  pending_commands: number;
  server_time: number;
  api_version: string;
}

export interface Position {
  id: number;
  symbol: string;
  side: 'long' | 'short';
  quantity: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number | null;
  initial_stop: number;
  highest_price: number;
  lowest_price: number;
  atr_at_entry: number | null;
  fees: number;
  mode: Mode;
  opened_at: string;
  current_price: number | null;
  unrealized_pnl: number | null;
  trailing_stop: number | null;
  trailing_active: boolean;
  close_pending: boolean;
}

export interface Trade {
  id: number;
  symbol: string;
  side: 'long' | 'short';
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  pnl: number | null;
  fees: number;
  exit_reason: string | null;
  mode: Mode;
  opened_at: string;
  closed_at: string | null;
}

export interface Pnl {
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  /** null when infinite (no losing trades); see profit_factor_infinite */
  profit_factor: number | null;
  profit_factor_infinite: boolean;
  expectancy: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  fees: number;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  starting_equity: number;
}

export interface Candle {
  t: number; // ms since epoch
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export type SettingValue = boolean | number | string;

export interface Setting {
  key: string;
  value: SettingValue;
  type: 'bool' | 'int' | 'float' | 'str';
  description: string;
  updated_at: string;
}

export interface LogEvent {
  id: number;
  timestamp: string;
  level: string;
  category: string;
  symbol: string | null;
  message: string;
  data: unknown;
}

export interface CloseResult {
  command_id: number;
  status: 'pending';
  already_queued: boolean;
}

export interface Command {
  id: number;
  command: string;
  payload: Record<string, unknown>;
  status: 'pending' | 'done' | 'failed';
  created_at: string;
  processed_at: string | null;
  note: string | null;
}

export type WsMessage =
  | { type: 'status'; data: Status }
  | { type: 'positions'; data: Position[] }
  | { type: 'logs'; data: LogEvent[] }
  | { type: 'ping'; data: { server_time: number } };
