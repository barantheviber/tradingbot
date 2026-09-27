import { Text, View } from 'react-native';
import Svg, { Line, Rect } from 'react-native-svg';

import type { Candle, Position } from '../api/types';
import { price } from '../lib/format';
import { colors } from '../lib/theme';

interface Props {
  candles: Candle[];
  positions?: Position[];
  height?: number;
}

/**
 * Minimal candlestick chart with entry / SL / TP lines for open positions.
 * Drawn in a fixed virtual coordinate space stretched to the full width, so it
 * needs no layout measurement.
 */
export function CandleChart({ candles, positions = [], height = 240 }: Props) {
  if (candles.length === 0) {
    return (
      <View style={{ height, justifyContent: 'center' }}>
        <Text style={{ color: colors.muted, textAlign: 'center' }}>Mum verisi yok</Text>
      </View>
    );
  }

  const levels = positions.flatMap((p) => [
    { y: p.entry_price, color: colors.accent },
    { y: p.stop_loss, color: colors.down },
    ...(p.take_profit ? [{ y: p.take_profit, color: colors.up }] : []),
  ]);
  const highs = candles.map((c) => c.h);
  const lows = candles.map((c) => c.l);
  const levelYs = levels.map((l) => l.y);
  const max = Math.max(...highs, ...levelYs);
  const min = Math.min(...lows, ...levelYs);
  const span = max - min || 1;
  const pad = 4;
  const y = (v: number) => pad + ((max - v) / span) * (height - pad * 2);
  const step = 10;
  const width = candles.length * step;
  const bodyW = Math.max(1, step * 0.6);
  const last = candles[candles.length - 1];

  return (
    <View>
      <Svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {levels.map((l, i) => (
          <Line key={`l${i}`} x1={0} x2={width} y1={y(l.y)} y2={y(l.y)} stroke={l.color} strokeDasharray="4 4" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        ))}
        {candles.map((c, i) => {
          const x = i * step + step / 2;
          const up = c.c >= c.o;
          const color = up ? colors.up : colors.down;
          const top = y(Math.max(c.o, c.c));
          const bottom = y(Math.min(c.o, c.c));
          return [
            <Line key={`w${c.t}`} x1={x} x2={x} y1={y(c.h)} y2={y(c.l)} stroke={color} strokeWidth={1} vectorEffect="non-scaling-stroke" />,
            <Rect key={`b${c.t}`} x={x - bodyW / 2} y={top} width={bodyW} height={Math.max(1, bottom - top)} fill={color} />,
          ];
        })}
      </Svg>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
        <Text style={{ color: colors.muted, fontSize: 11 }}>
          min {price(min)} · max {price(max)}
        </Text>
        <Text style={{ color: colors.text, fontSize: 11 }}>son {price(last.c)}</Text>
      </View>
    </View>
  );
}
