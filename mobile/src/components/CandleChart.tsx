import { useMemo, useState } from 'react';
import { Text, View, type GestureResponderEvent, type LayoutChangeEvent } from 'react-native';
import Svg, { Circle, Line, Polygon, Polyline, Rect, Text as SvgText } from 'react-native-svg';

import type { Candle, Position, Trade } from '../api/types';
import { price } from '../lib/format';
import { donchian, ema, timeframeMs, tradeMarks } from '../lib/indicators';
import { colors } from '../lib/theme';

interface Props {
  /** oldest first; may include warm-up candles before the `visible` ones shown */
  candles: Candle[];
  visible?: number;
  positions?: Position[];
  trades?: Trade[];
  symbol?: string | null;
  timeframe?: string | null;
  emaPeriod?: number;
  donchianPeriod?: number;
  height?: number;
}

const AXIS_W = 54;
const PAD_Y = 8;
const EMA_COLOR = '#d2a8ff';
const CHANNEL_COLOR = '#8b949e';

function points(values: (number | null)[], x: (i: number) => number, y: (v: number) => number): string[] {
  // one polyline per unbroken run of values
  const runs: string[] = [];
  let run: string[] = [];
  values.forEach((v, i) => {
    if (v === null) {
      if (run.length > 1) runs.push(run.join(' '));
      run = [];
    } else {
      run.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    }
  });
  if (run.length > 1) runs.push(run.join(' '));
  return runs;
}

function when(ms: number): string {
  return new Date(ms).toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

/**
 * Candlestick chart with the bot's trend EMA and Donchian channel, entry / exit marks of
 * closed trades, and entry / SL / TP lines of open positions. Tap or drag to read a candle.
 */
export function CandleChart({
  candles,
  visible = 120,
  positions = [],
  trades = [],
  symbol = null,
  timeframe = null,
  emaPeriod,
  donchianPeriod,
  height = 260,
}: Props) {
  const [width, setWidth] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);

  const view = useMemo(() => {
    const start = Math.max(0, candles.length - visible);
    const shown = candles.slice(start);
    const emaLine = emaPeriod ? ema(candles.map((c) => c.c), emaPeriod).slice(start) : [];
    const channel = donchianPeriod ? donchian(candles, donchianPeriod) : { upper: [], lower: [] };
    const tfMs = timeframeMs(timeframe) ?? (shown.length > 1 ? shown[1].t - shown[0].t : null);
    return {
      shown,
      emaLine,
      upper: channel.upper.slice(start),
      lower: channel.lower.slice(start),
      marks: symbol ? tradeMarks(trades, symbol, shown, tfMs) : [],
    };
  }, [candles, visible, emaPeriod, donchianPeriod, timeframe, trades, symbol]);

  const { shown, emaLine, upper, lower, marks } = view;
  if (shown.length === 0) {
    return (
      <View style={{ height, justifyContent: 'center' }}>
        <Text style={{ color: colors.muted, textAlign: 'center' }}>Mum verisi yok</Text>
      </View>
    );
  }

  const levels = positions.flatMap((p) => [
    { v: p.entry_price, color: colors.accent, label: 'Giriş' },
    { v: p.stop_loss, color: colors.down, label: 'SL' },
    ...(p.take_profit ? [{ v: p.take_profit, color: colors.up, label: 'TP' }] : []),
  ]);
  const inRange = [
    ...shown.flatMap((c) => [c.h, c.l]),
    ...levels.map((l) => l.v),
    ...[...emaLine, ...upper, ...lower].filter((v): v is number => v !== null),
  ];
  const max = Math.max(...inRange);
  const min = Math.min(...inRange);
  const span = max - min || Math.abs(max) || 1;

  const plotW = Math.max(1, width - AXIS_W);
  const step = plotW / shown.length;
  const bodyW = Math.max(1, step * 0.65);
  const x = (i: number) => i * step + step / 2;
  const y = (v: number) => PAD_Y + ((max - v) / span) * (height - PAD_Y * 2);
  const last = shown[shown.length - 1];
  const grid = [0, 1, 2, 3, 4].map((k) => max - (span * k) / 4);
  const pick = selected !== null && selected < shown.length ? selected : null;
  const mark = 5;

  const choose = (e: GestureResponderEvent) => {
    const i = Math.floor(e.nativeEvent.locationX / step);
    setSelected(Math.min(shown.length - 1, Math.max(0, i)));
  };

  return (
    <View>
      <View
        style={{ height }}
        onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)}
        onStartShouldSetResponder={() => true}
        onResponderGrant={choose}
        onResponderMove={choose}
      >
        {width > 0 ? (
          <Svg width={width} height={height} pointerEvents="none">
            {grid.map((g, k) => (
              <Line key={`g${k}`} x1={0} x2={plotW} y1={y(g)} y2={y(g)} stroke={colors.border} strokeWidth={0.5} />
            ))}
            {grid.map((g, k) => (
              <SvgText key={`gl${k}`} x={width - 2} y={y(g) + 3} fill={colors.muted} fontSize={9} fontFamily="sans-serif" textAnchor="end">
                {price(g)}
              </SvgText>
            ))}

            {points(upper, x, y).map((p, k) => (
              <Polyline key={`du${k}`} points={p} fill="none" stroke={CHANNEL_COLOR} strokeWidth={1} strokeDasharray="3 3" />
            ))}
            {points(lower, x, y).map((p, k) => (
              <Polyline key={`dl${k}`} points={p} fill="none" stroke={CHANNEL_COLOR} strokeWidth={1} strokeDasharray="3 3" />
            ))}

            {shown.map((c, i) => {
              const up = c.c >= c.o;
              const color = up ? colors.up : colors.down;
              const top = y(Math.max(c.o, c.c));
              const bottom = y(Math.min(c.o, c.c));
              return [
                <Line key={`w${c.t}`} x1={x(i)} x2={x(i)} y1={y(c.h)} y2={y(c.l)} stroke={color} strokeWidth={1} />,
                <Rect key={`b${c.t}`} x={x(i) - bodyW / 2} y={top} width={bodyW} height={Math.max(1, bottom - top)} fill={color} />,
              ];
            })}

            {points(emaLine, x, y).map((p, k) => (
              <Polyline key={`e${k}`} points={p} fill="none" stroke={EMA_COLOR} strokeWidth={1.5} />
            ))}

            {marks.map((m) => {
              const tone = m.win ? colors.up : colors.down;
              const out = [];
              if (m.entry && m.exit) {
                out.push(
                  <Line
                    key={`tl${m.id}`}
                    x1={x(m.entry.i)}
                    y1={y(m.entry.price)}
                    x2={x(m.exit.i)}
                    y2={y(m.exit.price)}
                    stroke={tone}
                    strokeWidth={1}
                    strokeDasharray="2 2"
                  />,
                );
              }
              if (m.entry) {
                const ex = x(m.entry.i);
                const ey = y(m.entry.price);
                // long: triangle pointing up under the price; short: pointing down above it
                const tri =
                  m.side === 'long'
                    ? `${ex},${ey + 2} ${ex - mark},${ey + 2 + mark * 1.6} ${ex + mark},${ey + 2 + mark * 1.6}`
                    : `${ex},${ey - 2} ${ex - mark},${ey - 2 - mark * 1.6} ${ex + mark},${ey - 2 - mark * 1.6}`;
                out.push(<Polygon key={`te${m.id}`} points={tri} fill={colors.accent} stroke={colors.bg} strokeWidth={0.5} />);
              }
              if (m.exit) {
                out.push(
                  <Circle key={`tx${m.id}`} cx={x(m.exit.i)} cy={y(m.exit.price)} r={3.5} fill={tone} stroke={colors.bg} strokeWidth={1} />,
                );
              }
              return out;
            })}

            {levels.map((l, i) => (
              <Line key={`l${i}`} x1={0} x2={plotW} y1={y(l.v)} y2={y(l.v)} stroke={l.color} strokeDasharray="5 4" strokeWidth={1} />
            ))}
            {levels.map((l, i) => (
              <SvgText key={`ll${i}`} x={4} y={y(l.v) - 3} fill={l.color} fontSize={9} fontFamily="sans-serif" fontWeight="bold">
                {l.label}
              </SvgText>
            ))}

            <Line x1={0} x2={plotW} y1={y(last.c)} y2={y(last.c)} stroke={colors.text} strokeWidth={0.5} strokeDasharray="1 3" />
            <Rect x={plotW + 1} y={y(last.c) - 7} width={AXIS_W - 1} height={14} rx={3} fill={last.c >= last.o ? colors.up : colors.down} />
            <SvgText x={width - 3} y={y(last.c) + 3.5} fill={colors.bg} fontSize={9.5} fontFamily="sans-serif" fontWeight="bold" textAnchor="end">
              {price(last.c)}
            </SvgText>

            {pick !== null ? (
              <Line x1={x(pick)} x2={x(pick)} y1={0} y2={height} stroke={colors.text} strokeWidth={0.75} strokeDasharray="2 2" />
            ) : null}
          </Svg>
        ) : null}
      </View>

      {pick !== null ? (
        <Text style={{ color: colors.text, fontSize: 11, marginTop: 4, fontVariant: ['tabular-nums'] }}>
          {when(shown[pick].t)} · A {price(shown[pick].o)} · Y {price(shown[pick].h)} · D {price(shown[pick].l)} · K{' '}
          {price(shown[pick].c)}
          {emaLine[pick] != null ? ` · EMA ${price(emaLine[pick])}` : ''}
        </Text>
      ) : (
        <Text style={{ color: colors.muted, fontSize: 11, marginTop: 4 }}>Bir mumun değerlerini görmek için grafiğe dokunun.</Text>
      )}

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', columnGap: 12, rowGap: 2, marginTop: 4 }}>
        {emaPeriod ? <Legend color={EMA_COLOR} text={`EMA ${emaPeriod} (trend)`} /> : null}
        {donchianPeriod ? <Legend color={CHANNEL_COLOR} text={`Donchian ${donchianPeriod}`} dashed /> : null}
        {marks.length ? <Legend color={colors.accent} text="▲ giriş" glyph /> : null}
        {marks.length ? <Legend color={colors.up} text="● kârla çıkış" glyph /> : null}
        {marks.length ? <Legend color={colors.down} text="● zararla çıkış" glyph /> : null}
      </View>
    </View>
  );
}

function Legend({ color, text, dashed, glyph }: { color: string; text: string; dashed?: boolean; glyph?: boolean }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
      {glyph ? null : (
        <View style={{ width: 14, height: 0, borderTopWidth: 1.5, borderColor: color, borderStyle: dashed ? 'dashed' : 'solid' }} />
      )}
      <Text style={{ color: glyph ? color : colors.muted, fontSize: 11 }}>{text}</Text>
    </View>
  );
}
