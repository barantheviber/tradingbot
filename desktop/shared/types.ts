// API contract types (shared with the mobile app) plus the IPC bridge between
// Electron's main process and the renderer.

import type { SettingValue, WsMessage } from "./apiTypes";
import type { LocalBotState, LocalSetup } from "./localBot";
import type { UpdateInfo } from "./updateCheck";

export * from "./apiTypes";
export * from "./localBot";

/** Live messages the main process forwards to the renderer (pings stay in main). */
export type WsEvent = Exclude<WsMessage, { type: "ping" }>;

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
  | { kind: "command"; id: number }
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
  /** The bot this app runs on this computer. */
  localBot: {
    getState(): Promise<LocalBotState>;
    getSetup(): Promise<LocalSetup | null>;
    saveSetup(setup: LocalSetup): Promise<LocalBotState>;
    start(): Promise<LocalBotState>;
    stop(): Promise<LocalBotState>;
    onState(listener: (state: LocalBotState) => void): () => void;
    openLogFolder(): Promise<void>;
    /** Open the app when Windows starts (installed app only; supported is false in development). */
    getOpenAtLogin(): Promise<{ supported: boolean; enabled: boolean }>;
    setOpenAtLogin(enabled: boolean): Promise<void>;
  };
  /** "Yeni sürüm var": looks for a newer release at most once a day; never downloads anything. */
  updates: {
    check(): Promise<UpdateInfo | null>;
    dismiss(version: string): Promise<void>;
    openPage(version: string): Promise<void>;
  };
}
