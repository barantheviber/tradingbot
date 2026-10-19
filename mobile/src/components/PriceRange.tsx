import { Text, View } from 'react-native';

import type { Position } from '../api/types';
import { price } from '../lib/format';
import { colors } from '../lib/theme';

/**
 * Where the price sits between the stop and the take-profit: the stop on the left, the
 * target on the right, whatever the side, so "further right" is always "going our way".
 */
export function PriceRange({ p }: { p: Position }) {
  const current = p.current_price;
  const target = p.take_profit;
  if (current === null || target === null) return null;
  const long = p.side === 'long';
  // progress from the stop (0) to the target (1)
  const at = (v: number) => (long ? (v - p.stop_loss) / (target - p.stop_loss) : (p.stop_loss - v) / (p.stop_loss - target));
  const clamp = (f: number) => Math.min(1, Math.max(0, f));
  const now = at(current);
  const entry = at(p.entry_price);
  if (!Number.isFinite(now) || !Number.isFinite(entry)) return null;
  const gaining = now >= entry;

  return (
    <View style={{ marginTop: 8, marginBottom: 2 }}>
      <View style={{ height: 8, borderRadius: 4, backgroundColor: colors.border, overflow: 'hidden' }}>
        <View
          style={{
            position: 'absolute',
            left: `${clamp(Math.min(entry, now)) * 100}%`,
            width: `${Math.abs(clamp(now) - clamp(entry)) * 100}%`,
            top: 0,
            bottom: 0,
            backgroundColor: gaining ? colors.up : colors.down,
          }}
        />
      </View>
      {/* entry tick and current price marker */}
      <View style={{ position: 'absolute', left: `${clamp(entry) * 100}%`, top: -2, width: 2, height: 12, marginLeft: -1, backgroundColor: colors.accent }} />
      <View
        style={{
          position: 'absolute',
          left: `${clamp(now) * 100}%`,
          top: -3,
          width: 14,
          height: 14,
          marginLeft: -7,
          borderRadius: 7,
          borderWidth: 2,
          borderColor: colors.bg,
          backgroundColor: colors.text,
        }}
      />
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
        <Text style={{ color: colors.down, fontSize: 11 }}>SL {price(p.stop_loss)}</Text>
        <Text style={{ color: colors.accent, fontSize: 11 }}>giriş {price(p.entry_price)}</Text>
        <Text style={{ color: colors.up, fontSize: 11 }}>TP {price(target)}</Text>
      </View>
    </View>
  );
}
