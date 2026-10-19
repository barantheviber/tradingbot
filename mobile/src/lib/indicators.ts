// Chart overlays computed on the phone from the candles the API returns. They follow
// strategy.py (pandas ewm(adjust=False, min_periods=period); Donchian over the previous N
// candles) so the lines match what the bot compares against.
import type { Candle, Trade } from '../api/types';

/** EMA of the closes; null until `period` candles are in. */
export function ema(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  if (period < 1) return values.map(() => null);
  const alpha = 2 / (period + 1);
  let prev: number | null = null;
  values.forEach((v, i) => {
    prev = prev === null ? v : alpha * v + (1 - alpha) * prev;
    out.push(i >= period - 1 ? prev : null);
  });
  return out;
}

/** Highest high / lowest low of the previous `period` candles (the current one excluded). */
export function donchian(candles: Candle[], period: number): { upper: (number | null)[]; lower: (number | null)[] } {
  const upper: (number | null)[] = [];
  const lower: (number | null)[] = [];
  candles.forEach((_, i) => {
    if (period < 1 || i < period) {
      upper.push(null);
      lower.push(null);
      return;
    }
    let hi = -Infinity;
    let lo = Infinity;
    for (let j = i - period; j < i; j++) {
      hi = Math.max(hi, candles[j].h);
      lo = Math.min(lo, candles[j].l);
    }
    upper.push(hi);
    lower.push(lo);
  });
  return { upper, lower };
}

const UNIT_MS: Record<string, number> = { s: 1_000, m: 60_000, h: 3_600_000, d: 86_400_000, w: 604_800_000, M: 2_592_000_000 };

/** "4h" -> 14 400 000; null for anything the bot would not accept. */
export function timeframeMs(timeframe: string | null | undefined): number | null {
  const m = /^(\d+)([smhdwM])$/.exec(timeframe ?? '');
  return m ? Number(m[1]) * UNIT_MS[m[2]] : null;
}

/** Index of the candle that contains `ms`, or null when it is outside the candles shown. */
export function candleIndexAt(candles: Candle[], ms: number, tfMs: number): number | null {
  if (candles.length === 0 || ms < candles[0].t || ms >= candles[candles.length - 1].t + tfMs) return null;
  let lo = 0;
  let hi = candles.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (candles[mid].t <= ms) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

export interface TradeMark {
  id: number;
  side: 'long' | 'short';
  win: boolean;
  entry: { i: number; price: number } | null;
  exit: { i: number; price: number } | null;
}

/** Where each closed trade of `symbol` opened and closed on the candles shown. */
export function tradeMarks(trades: Trade[], symbol: string, candles: Candle[], tfMs: number | null): TradeMark[] {
  if (!tfMs) return [];
  const marks: TradeMark[] = [];
  for (const t of trades) {
    if (t.symbol !== symbol) continue;
    const openedMs = Date.parse(t.opened_at);
    const closedMs = t.closed_at ? Date.parse(t.closed_at) : NaN;
    const ei = Number.isNaN(openedMs) ? null : candleIndexAt(candles, openedMs, tfMs);
    const xi = Number.isNaN(closedMs) || t.exit_price === null ? null : candleIndexAt(candles, closedMs, tfMs);
    if (ei === null && xi === null) continue;
    marks.push({
      id: t.id,
      side: t.side,
      win: (t.pnl ?? 0) > 0,
      entry: ei === null ? null : { i: ei, price: t.entry_price },
      exit: xi === null || t.exit_price === null ? null : { i: xi, price: t.exit_price },
    });
  }
  return marks;
}

export interface CurvePoint {
  t: number; // ms since epoch
  value: number;
}

/** Running total of realized PnL, oldest trade first, starting from 0 at the first entry. */
export function pnlCurve(trades: Trade[]): CurvePoint[] {
  const closed = trades
    .filter((t) => t.closed_at && t.pnl !== null && !Number.isNaN(Date.parse(t.closed_at)))
    .sort((a, b) => Date.parse(a.closed_at as string) - Date.parse(b.closed_at as string) || a.id - b.id);
  if (closed.length === 0) return [];
  const first = Math.min(...closed.map((t) => Date.parse(t.opened_at)).filter((n) => !Number.isNaN(n)), Date.parse(closed[0].closed_at as string));
  const points: CurvePoint[] = [{ t: first, value: 0 }];
  let total = 0;
  for (const t of closed) {
    total += t.pnl as number;
    points.push({ t: Date.parse(t.closed_at as string), value: total });
  }
  return points;
}

/** Largest fall from a running peak, in the curve's own units (0 when it never fell). */
export function maxDrawdown(points: CurvePoint[]): number {
  let peak = -Infinity;
  let worst = 0;
  for (const p of points) {
    peak = Math.max(peak, p.value);
    worst = Math.max(worst, peak - p.value);
  }
  return worst;
}
