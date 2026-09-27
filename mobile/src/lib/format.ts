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
