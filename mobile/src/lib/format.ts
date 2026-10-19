export function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return value.toLocaleString('tr-TR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Prices span many magnitudes (BTC vs. small caps): keep ~6 significant digits. */
export function price(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  return value.toLocaleString('tr-TR', { maximumSignificantDigits: 6 });
}

export function signed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '-';
  return `${value > 0 ? '+' : ''}${num(value, digits)}`;
}

export function pct(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? '-' : `%${num(value, digits)}`;
}

export function time(iso: string | null | undefined): string {
  if (!iso) return '-';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' });
}

export function age(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'heartbeat yok';
  seconds = Math.max(0, seconds);
  if (seconds < 120) return `${Math.round(seconds)} sn önce`;
  return `${Math.round(seconds / 60)} dk önce`;
}

/** "3 g 4 sa", "2 sa 15 dk", "12 dk" */
export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '-';
  const minutes = Math.max(0, Math.round(ms / 60_000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days > 0) return hours ? `${days} g ${hours} sa` : `${days} g`;
  if (hours > 0) return mins ? `${hours} sa ${mins} dk` : `${hours} sa`;
  return `${mins} dk`;
}

/** Time between two ISO timestamps (the second defaults to now). */
export function between(fromIso: string | null | undefined, toIso?: string | null): string {
  if (!fromIso) return '-';
  const to = toIso ? Date.parse(toIso) : Date.now();
  return duration(to - Date.parse(fromIso));
}

// The bot's exit reasons (bot_engine.py / risk_manager.check_exit); unknown ones are shown as they are.
const EXIT_REASONS: Record<string, string> = {
  stop_loss: 'Stop',
  take_profit: 'Kâr al',
  trailing_stop: 'Trailing stop',
  trend_flip: 'Trend döndü',
  manual: 'Elle kapatıldı',
};

export function exitReason(reason: string | null | undefined): string {
  if (!reason) return '-';
  const partial = reason.endsWith(' (partial)');
  const key = partial ? reason.slice(0, -' (partial)'.length) : reason;
  const label = EXIT_REASONS[key] ?? key;
  return partial ? `${label} (kısmi)` : label;
}

/** "+%1,25" / "-%0,40" */
export function signedPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return `${value > 0 ? '+' : value < 0 ? '-' : ''}%${num(Math.abs(value), digits)}`;
}
