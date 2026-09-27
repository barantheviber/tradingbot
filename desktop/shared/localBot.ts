// The bot that runs on this computer: the setup the user picks on first run and the
// state of the bundled bot process. Shared by the main process and the renderer.

export type MarketType = "spot" | "future" | "swap";

export interface LocalSetup {
  exchangeId: string;
  marketType: MarketType;
  symbols: string[];
  timeframe: string;
  startingBalance: number;
}

export type LocalBotPhase = "stopped" | "starting" | "running" | "stopping" | "restarting" | "error";

export interface LocalBotState {
  /** false when the app is pointed at an external API (development), so it runs no bot itself */
  managed: boolean;
  setupDone: boolean;
  phase: LocalBotPhase;
  /** plain-language reason for "error" / "restarting" */
  message: string | null;
}

export const EXCHANGES: { id: string; label: string }[] = [
  { id: "binance", label: "Binance" },
  { id: "bybit", label: "Bybit" },
  { id: "okx", label: "OKX" },
  { id: "kucoin", label: "KuCoin" },
  { id: "gateio", label: "Gate.io" },
  { id: "bitget", label: "Bitget" },
  { id: "kraken", label: "Kraken" },
];

export const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

export const DEFAULT_SETUP: LocalSetup = {
  exchangeId: "binance",
  marketType: "spot",
  symbols: ["BTC/USDT", "ETH/USDT"],
  timeframe: "1h",
  startingBalance: 10000,
};

const SYMBOL_RE = /^[A-Z0-9]{1,20}\/[A-Z0-9]{1,20}(:[A-Z0-9]{1,20})?$/;

/** Parses "btc/usdt, eth/usdt" into ["BTC/USDT", "ETH/USDT"]. */
export function parseSymbols(text: string): string[] {
  return [...new Set(text.split(/[,\s]+/).map((s) => s.trim().toUpperCase()).filter(Boolean))];
}

/** Returns a list of problems in Turkish; empty when the setup can be used. */
export function validateSetup(s: LocalSetup): string[] {
  const problems: string[] = [];
  if (!EXCHANGES.some((e) => e.id === s.exchangeId)) problems.push("Borsa listeden seçilmeli.");
  if (!["spot", "future", "swap"].includes(s.marketType)) problems.push("Piyasa türü geçersiz.");
  if (!Array.isArray(s.symbols) || s.symbols.length === 0) problems.push("En az bir sembol girin (ör. BTC/USDT).");
  else if (s.symbols.length > 20) problems.push("En fazla 20 sembol girilebilir.");
  else {
    const bad = s.symbols.filter((sym) => !SYMBOL_RE.test(sym));
    if (bad.length) problems.push(`Sembol biçimi COIN/KOTASYON olmalı (ör. BTC/USDT): ${bad.join(", ")}`);
  }
  if (!TIMEFRAMES.includes(s.timeframe)) problems.push("Zaman dilimi listeden seçilmeli.");
  if (!Number.isFinite(s.startingBalance) || s.startingBalance <= 0 || s.startingBalance > 1e9)
    problems.push("Başlangıç bakiyesi 0'dan büyük bir sayı olmalı.");
  return problems;
}
