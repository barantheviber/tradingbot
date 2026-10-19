import { useMemo, useState } from 'react';
import { Text, View, type LayoutChangeEvent } from 'react-native';
import Svg, { Circle, Defs, Line, LinearGradient, Path, Polyline, Stop, Text as SvgText } from 'react-native-svg';

import type { Trade } from '../api/types';
import { num, pct, signed, time } from '../lib/format';
import { maxDrawdown, pnlCurve } from '../lib/indicators';
import { colors, pnlColor } from '../lib/theme';

interface Props {
  trades: Trade[];
  /** open positions' PnL, drawn as a last "now" point */
  unrealized?: number | null;
  /** paper starting balance; 0 in live mode, where no percentages are shown */
  startingEquity?: number;
  height?: number;
}

/** Running total of realized PnL over closed trades, with the open positions' PnL on top. */
export function PnlCurve({ trades, unrealized, startingEquity = 0, height = 150 }: Props) {
  const [width, setWidth] = useState(0);
  const curve = useMemo(() => pnlCurve(trades), [trades]);

  if (curve.length === 0) {
    return <Text style={{ color: colors.muted, paddingVertical: 12 }}>Kapanmış işlem olunca burada PnL eğrisi görünür.</Text>;
  }

  const realized = curve[curve.length - 1].value;
  const now = unrealized ? realized + unrealized : null;
  const values = [...curve.map((p) => p.value), ...(now !== null ? [now] : [])];
  const max = Math.max(0, ...values);
  const min = Math.min(0, ...values);
  const span = max - min || 1;
  const pad = 8;
  const n = values.length;
  const x = (i: number) => pad + (i / Math.max(1, n - 1)) * (width - pad * 2);
  const y = (v: number) => pad + ((max - v) / span) * (height - pad * 2);
  const line = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `M${x(0)},${y(0)} L${values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' L')} L${x(n - 1)},${y(0)} Z`;
  const tone = realized >= 0 ? colors.up : colors.down;
  const dd = maxDrawdown(curve);
  const peak = Math.max(...curve.map((p) => p.value));

  return (
    <View>
      <View style={{ height }} onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)}>
        {width > 0 ? (
          <Svg width={width} height={height}>
            <Defs>
              <LinearGradient id="pnlFill" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={tone} stopOpacity={0.35} />
                <Stop offset="1" stopColor={tone} stopOpacity={0.02} />
              </LinearGradient>
            </Defs>
            <Line x1={0} x2={width} y1={y(0)} y2={y(0)} stroke={colors.border} strokeDasharray="4 4" />
            <SvgText x={width - 2} y={y(0) - 3} fill={colors.muted} fontSize={9} fontFamily="sans-serif" textAnchor="end">
              0
            </SvgText>
            <Path d={area} fill="url(#pnlFill)" />
            <Polyline points={line} fill="none" stroke={tone} strokeWidth={2} />
            {now !== null ? (
              <>
                <Line x1={x(n - 2)} y1={y(realized)} x2={x(n - 1)} y2={y(now)} stroke={colors.accent} strokeWidth={2} strokeDasharray="3 3" />
                <Circle cx={x(n - 1)} cy={y(now)} r={3.5} fill={colors.accent} />
              </>
            ) : (
              <Circle cx={x(n - 1)} cy={y(realized)} r={3.5} fill={tone} />
            )}
          </Svg>
        ) : null}
      </View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 }}>
        <Text style={{ color: colors.muted, fontSize: 11 }}>{time(new Date(curve[0].t).toISOString())}</Text>
        <Text style={{ color: colors.muted, fontSize: 11 }}>
          {curve.length - 1} işlem{now !== null ? ' · mavi: açık pozisyonlarla' : ''}
        </Text>
      </View>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', columnGap: 16, rowGap: 4, marginTop: 6 }}>
        <Figure
          label="Gerçekleşen"
          value={signed(realized)}
          hint={startingEquity > 0 ? pct((realized / startingEquity) * 100) : undefined}
          color={pnlColor(realized)}
        />
        <Figure label="Zirve" value={signed(peak)} />
        <Figure
          label="En büyük düşüş"
          value={dd > 0 ? `-${num(dd)}` : num(0)}
          hint={startingEquity > 0 && dd > 0 ? pct((dd / (startingEquity + Math.max(0, peak))) * 100) : undefined}
          color={dd > 0 ? colors.down : undefined}
        />
      </View>
    </View>
  );
}

function Figure({ label, value, hint, color }: { label: string; value: string; hint?: string; color?: string }) {
  return (
    <View>
      <Text style={{ color: colors.muted, fontSize: 11 }}>{label}</Text>
      <Text style={{ color: color ?? colors.text, fontSize: 14, fontWeight: '600', fontVariant: ['tabular-nums'] }}>
        {value}
        {hint ? <Text style={{ color: colors.muted, fontSize: 11, fontWeight: '400' }}> {hint}</Text> : null}
      </Text>
    </View>
  );
}
