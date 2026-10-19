import { useFocusEffect } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, Text, View } from 'react-native';

import { api } from '../../api/client';
import type { Trade } from '../../api/types';
import { Banner, Card, Chip, Empty, Row, Stat, styles } from '../../components/ui';
import { useRequiredConnection } from '../../lib/connection';
import { between, exitReason, num, pct, price, signed, signedPct, time } from '../../lib/format';
import { colors, pnlColor } from '../../lib/theme';

type Outcome = 'all' | 'win' | 'loss';

const OUTCOMES: { key: Outcome; label: string }[] = [
  { key: 'all', label: 'Hepsi' },
  { key: 'win', label: 'Kârlı' },
  { key: 'loss', label: 'Zararlı' },
];

// Same split as performance.py: a trade that made nothing counts as a loss.
const isWin = (t: Trade) => (t.pnl ?? 0) > 0;

function returnPct(t: Trade): number | null {
  if (t.pnl === null || !t.entry_price || !t.quantity) return null;
  return (t.pnl / (t.entry_price * t.quantity)) * 100;
}

function TradeCard({ t, open, onToggle }: { t: Trade; open: boolean; onToggle: () => void }) {
  const ret = returnPct(t);
  return (
    <Pressable onPress={onToggle} accessibilityRole="button" accessibilityState={{ expanded: open }}>
      <View style={[styles.card, { paddingVertical: 10 }]}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
          <Text style={[styles.text, { fontWeight: '600' }]}>
            #{t.id} {t.symbol}{' '}
            <Text style={{ color: t.side === 'long' ? colors.up : colors.down }}>{t.side === 'long' ? 'LONG' : 'SHORT'}</Text>
          </Text>
          <Text style={{ color: pnlColor(t.pnl), fontWeight: '600', fontVariant: ['tabular-nums'] }}>
            {signed(t.pnl)}
            {ret !== null ? <Text style={{ fontSize: 11, fontWeight: '400' }}> ({signedPct(ret)})</Text> : null}
          </Text>
        </View>
        <Text style={styles.muted}>
          {price(t.entry_price)} → {price(t.exit_price)} · {exitReason(t.exit_reason)} · {time(t.closed_at)}
        </Text>
        {open ? (
          <View style={{ marginTop: 8, borderTopWidth: 1, borderColor: colors.border, paddingTop: 6 }}>
            <Row label="Miktar" value={String(t.quantity)} />
            <Row label="Büyüklük (giriş)" value={num(t.entry_price * t.quantity)} />
            <Row label="Açılış" value={time(t.opened_at)} />
            <Row label="Kapanış" value={time(t.closed_at)} />
            <Row label="Süre" value={between(t.opened_at, t.closed_at)} />
            <Row label="Kapanma sebebi" value={exitReason(t.exit_reason)} />
            <Row label="Komisyon" value={num(t.fees)} />
            <Row label="Net PnL" value={signed(t.pnl)} color={pnlColor(t.pnl)} />
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}

export default function TradesScreen() {
  const connection = useRequiredConnection();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [symbol, setSymbol] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome>('all');
  const [openId, setOpenId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setTrades(await api.trades(connection, 500));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [connection]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const symbols = useMemo(() => [...new Set(trades.map((t) => t.symbol))].sort(), [trades]);
  const shown = useMemo(
    () =>
      trades.filter(
        (t) =>
          (symbol === null || t.symbol === symbol) &&
          (outcome === 'all' || (outcome === 'win' ? isWin(t) : !isWin(t))),
      ),
    [trades, symbol, outcome],
  );
  const summary = useMemo(() => {
    const bySymbol = trades.filter((t) => symbol === null || t.symbol === symbol);
    const wins = bySymbol.filter(isWin);
    const total = bySymbol.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
    const best = bySymbol.reduce<number | null>((m, t) => (t.pnl === null ? m : m === null ? t.pnl : Math.max(m, t.pnl)), null);
    const worst = bySymbol.reduce<number | null>((m, t) => (t.pnl === null ? m : m === null ? t.pnl : Math.min(m, t.pnl)), null);
    return {
      count: bySymbol.length,
      wins: wins.length,
      total,
      winRate: bySymbol.length ? (wins.length / bySymbol.length) * 100 : null,
      best,
      worst,
    };
  }, [trades, symbol]);

  const header = (
    <View style={{ gap: 12 }}>
      {error ? <Banner tone="error" text={error} /> : null}
      {trades.length ? (
        <Card title={symbol ? `Özet · ${symbol}` : 'Özet'}>
          <View style={styles.statGrid}>
            <Stat label="Toplam PnL" value={signed(summary.total)} color={pnlColor(summary.total)} />
            <Stat
              label="Kazanma oranı"
              value={pct(summary.winRate, 1)}
              hint={`${summary.wins} kârlı / ${summary.count - summary.wins} zararlı`}
            />
            <Stat label="En iyi işlem" value={signed(summary.best)} color={pnlColor(summary.best)} />
            <Stat label="En kötü işlem" value={signed(summary.worst)} color={pnlColor(summary.worst)} />
          </View>
        </Card>
      ) : null}
      {symbols.length > 1 ? (
        <View style={styles.chipRow}>
          <Chip label="Tüm semboller" active={symbol === null} onPress={() => setSymbol(null)} />
          {symbols.map((s) => (
            <Chip key={s} label={s} active={symbol === s} onPress={() => setSymbol(s)} />
          ))}
        </View>
      ) : null}
      {trades.length ? (
        <View style={styles.chipRow}>
          {OUTCOMES.map((o) => (
            <Chip
              key={o.key}
              label={o.label}
              active={outcome === o.key}
              color={o.key === 'win' ? colors.up : o.key === 'loss' ? colors.down : undefined}
              onPress={() => setOutcome(o.key)}
            />
          ))}
          <Text style={[styles.muted, { alignSelf: 'center', marginLeft: 4 }]}>{shown.length} işlem · ayrıntı için dokunun</Text>
        </View>
      ) : null}
    </View>
  );

  return (
    <FlatList
      style={styles.screen}
      contentContainerStyle={styles.content}
      data={shown}
      keyExtractor={(t) => String(t.id)}
      ListHeaderComponent={header}
      ListEmptyComponent={<Empty text={trades.length ? 'Bu filtreye uyan işlem yok.' : 'Henüz kapanmış işlem yok.'} />}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={colors.accent}
          onRefresh={async () => {
            setRefreshing(true);
            await load();
            setRefreshing(false);
          }}
        />
      }
      renderItem={({ item }) => (
        <TradeCard t={item} open={openId === item.id} onToggle={() => setOpenId(openId === item.id ? null : item.id)} />
      )}
    />
  );
}
