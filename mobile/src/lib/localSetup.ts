// The phone's own bot: the setup the user picks, and what is sent to the native BotService.
// Same rules as desktop/shared/localBot.ts (keep the two in sync).

export type MarketType = 'spot' | 'future' | 'swap';

export interface LocalSetup {
  exchangeId: string;
  marketType: MarketType;
  symbols: string[];
  timeframe: string;
  startingBalance: number;
}

/** The on-phone API listens here only; nothing on the network can reach it. */
export const LOCAL_API_PORT = 47821;
export const LOCAL_BASE_URL = `http://127.0.0.1:${LOCAL_API_PORT}`;

export const EXCHANGES: { id: string; label: string }[] = [
  { id: 'binance', label: 'Binance' },
  { id: 'bybit', label: 'Bybit' },
  { id: 'okx', label: 'OKX' },
  { id: 'kucoin', label: 'KuCoin' },
  { id: 'gateio', label: 'Gate.io' },
  { id: 'bitget', label: 'Bitget' },
  { id: 'kraken', label: 'Kraken' },
];

export const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d'];

export const DEFAULT_SETUP: LocalSetup = {
  exchangeId: 'binance',
  marketType: 'spot',
  symbols: ['BTC/USDT', 'ETH/USDT'],
  timeframe: '1h',
  startingBalance: 10000,
};

const SYMBOL_RE = /^[A-Z0-9]{1,20}\/[A-Z0-9]{1,20}(:[A-Z0-9]{1,20})?$/;

export function parseSymbols(text: string): string[] {
  return [...new Set(text.split(/[,\s]+/).map((s) => s.trim().toUpperCase()).filter(Boolean))];
}

export function validateSetup(s: LocalSetup): string[] {
  const problems: string[] = [];
  if (!EXCHANGES.some((e) => e.id === s.exchangeId)) problems.push('Borsa listeden seçilmeli.');
  if (!['spot', 'future', 'swap'].includes(s.marketType)) problems.push('Piyasa türü geçersiz.');
  if (!Array.isArray(s.symbols) || s.symbols.length === 0) problems.push('En az bir sembol girin (ör. BTC/USDT).');
  else if (s.symbols.length > 20) problems.push('En fazla 20 sembol girilebilir.');
  else {
    const bad = s.symbols.filter((sym) => !SYMBOL_RE.test(sym));
    if (bad.length) problems.push(`Sembol biçimi COIN/KOTASYON olmalı (ör. BTC/USDT): ${bad.join(', ')}`);
  }
  if (!TIMEFRAMES.includes(s.timeframe)) problems.push('Zaman dilimi listeden seçilmeli.');
  if (!Number.isFinite(s.startingBalance) || s.startingBalance <= 0 || s.startingBalance > 1e9)
    problems.push("Başlangıç bakiyesi 0'dan büyük bir sayı olmalı.");
  return problems;
}

/** JSON for BotService / android_runtime.py. Paper mode is forced on the Python side too. */
export function runtimeConfig(setup: LocalSetup, token: string): string {
  return JSON.stringify({
    env: {
      EXCHANGE_ID: setup.exchangeId,
      MARKET_TYPE: setup.marketType,
      SYMBOLS: setup.symbols.join(','),
      TIMEFRAME: setup.timeframe,
      PAPER_STARTING_BALANCE: String(setup.startingBalance),
      API_PORT: String(LOCAL_API_PORT),
      API_TOKEN: token,
    },
  });
}

