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

/** Preset and marked "önerilen": in the real-data backtests short timeframes lose more to fees. */
export const RECOMMENDED_TIMEFRAME = "4h";

const CANDLE_TR: Record<string, string> = {
  "1m": "1 dakikalık",
  "5m": "5 dakikalık",
  "15m": "15 dakikalık",
  "30m": "30 dakikalık",
  "1h": "1 saatlik",
  "4h": "4 saatlik",
  "1d": "günlük",
};

/** "4h" -> "4h (önerilen)" for the setup picker. */
export function timeframeLabel(tf: string): string {
  return tf === RECOMMENDED_TIMEFRAME ? `${tf} (önerilen)` : tf;
}

/** First-run line on how often the bot decides, e.g. for "4h": only when a 4-hour candle closes. */
export function candleNote(tf: string | null): string {
  const candle = (tf && CANDLE_TR[tf]) || null;
  return candle
    ? `Bot yalnızca ${candle} mum kapandığında karar verir. Bu yüzden saatlerce hiç işlem olmaması normaldir.`
    : "Bot yalnızca mum kapandığında karar verir. Bu yüzden uzun süre hiç işlem olmaması normaldir.";
}

const UNIT_MS: Record<string, number> = { m: 60_000, h: 3_600_000, d: 86_400_000 };

/**
 * When the current candle closes, in ms. Exchange candles up to 1d start at whole multiples of their
 * length since 1970-01-01 UTC, so the close is the next multiple. Null for anything else (e.g. 1w).
 */
export function nextCandleClose(tf: string, nowMs: number): number | null {
  const m = /^(\d+)([mhd])$/.exec(tf);
  if (!m) return null;
  const len = Number(m[1]) * UNIT_MS[m[2]];
  if (!(len > 0) || UNIT_MS.d % len !== 0) return null;
  return (Math.floor(nowMs / len) + 1) * len;
}

/** 135 minutes -> "2 sa 15 dk". */
export function durationText(ms: number): string {
  const min = Math.max(1, Math.ceil(ms / 60_000));
  if (min < 60) return `${min} dk`;
  const h = Math.floor(min / 60);
  const rest = min % 60;
  return rest ? `${h} sa ${rest} dk` : `${h} sa`;
}

/** "Sonraki mum kapanışı 20:00 (2 sa 15 dk sonra)" in local time; the bot decides within a poll of it. */
export function nextDecisionText(tf: string, nowMs: number): string | null {
  const at = nextCandleClose(tf, nowMs);
  if (at === null) return null;
  const d = new Date(at);
  const clock = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return `Sonraki mum kapanışı ${clock} (${durationText(at - nowMs)} sonra)`;
}

export const DEFAULT_SETUP: LocalSetup = {
  exchangeId: "binance",
  marketType: "spot",
  symbols: ["BTC/USDT", "ETH/USDT"],
  timeframe: RECOMMENDED_TIMEFRAME,
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
