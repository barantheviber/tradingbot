import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type ViewStyle } from 'react-native';

import { colors } from '../lib/theme';

export function Card({ title, children, style }: { title?: string; children: ReactNode; style?: ViewStyle }) {
  return (
    <View style={[styles.card, style]}>
      {title ? <Text style={styles.cardTitle}>{title}</Text> : null}
      {children}
    </View>
  );
}

export function Stat({ label, value, color, hint }: { label: string; value: string; color?: string; hint?: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={[styles.statValue, color ? { color } : null]}>{value}</Text>
      {hint ? <Text style={styles.statHint}>{hint}</Text> : null}
    </View>
  );
}

export function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, color ? { color } : null]}>{value}</Text>
    </View>
  );
}

export function Banner({ text, tone = 'warn' }: { text: string; tone?: 'warn' | 'error' | 'info' }) {
  const bg = tone === 'error' ? colors.down : tone === 'info' ? colors.accent : colors.warn;
  return (
    <View style={[styles.banner, { borderColor: bg }]}>
      <Text style={[styles.bannerText, { color: bg }]}>{text}</Text>
    </View>
  );
}

export function Button({
  label,
  onPress,
  tone = 'default',
  disabled,
  busy,
}: {
  label: string;
  onPress: () => void;
  tone?: 'default' | 'primary' | 'danger';
  disabled?: boolean;
  busy?: boolean;
}) {
  const bg = tone === 'danger' ? colors.down : tone === 'primary' ? colors.accent : colors.border;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled || busy}
      style={({ pressed }) => [styles.button, { backgroundColor: bg, opacity: disabled ? 0.4 : pressed ? 0.7 : 1 }]}
    >
      {busy ? <ActivityIndicator color={colors.text} /> : <Text style={styles.buttonText}>{label}</Text>}
    </Pressable>
  );
}

export function Empty({ text }: { text: string }) {
  return <Text style={styles.empty}>{text}</Text>;
}

export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 12, gap: 12 },
  card: { backgroundColor: colors.card, borderColor: colors.border, borderWidth: 1, borderRadius: 10, padding: 12 },
  cardTitle: { color: colors.text, fontSize: 16, fontWeight: '600', marginBottom: 8 },
  stat: { flexBasis: '48%', flexGrow: 1, paddingVertical: 6 },
  statLabel: { color: colors.muted, fontSize: 12 },
  statValue: { color: colors.text, fontSize: 18, fontWeight: '600', marginTop: 2 },
  statHint: { color: colors.muted, fontSize: 11, marginTop: 2 },
  statGrid: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 8 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3 },
  rowLabel: { color: colors.muted, fontSize: 13 },
  rowValue: { color: colors.text, fontSize: 13, fontVariant: ['tabular-nums'] },
  banner: { borderWidth: 1, borderRadius: 8, padding: 10 },
  bannerText: { fontSize: 13 },
  button: { borderRadius: 8, paddingVertical: 10, paddingHorizontal: 14, alignItems: 'center' },
  buttonText: { color: colors.text, fontWeight: '600' },
  empty: { color: colors.muted, textAlign: 'center', padding: 24 },
  text: { color: colors.text },
  muted: { color: colors.muted, fontSize: 12 },
  input: {
    color: colors.text,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    backgroundColor: colors.bg,
  },
});
