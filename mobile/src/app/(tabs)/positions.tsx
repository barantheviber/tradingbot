import { useState } from 'react';
import { Alert, FlatList, Platform, RefreshControl, Text, View } from 'react-native';

import { api } from '../../api/client';
import type { Position } from '../../api/types';
import { PriceRange } from '../../components/PriceRange';
import { Banner, Button, Card, Empty, Row, styles } from '../../components/ui';
import { useRequiredConnection } from '../../lib/connection';
import { between, num, price, signed, signedPct, time } from '../../lib/format';
import { useLive } from '../../lib/live';
import { colors, pnlColor } from '../../lib/theme';

/** Open PnL in units of the risk taken at entry (distance to the first stop x quantity). */
function rMultiple(p: Position): number | null {
  const risk = Math.abs(p.entry_price - p.initial_stop) * p.quantity;
  return p.unrealized_pnl === null || !risk ? null : p.unrealized_pnl / risk;
}

/** How far the price may still move against the position before the stop, % of the price. */
function stopDistancePct(p: Position): number | null {
  if (!p.current_price) return null;
  return ((p.side === 'long' ? p.current_price - p.stop_loss : p.stop_loss - p.current_price) / p.current_price) * 100;
}

function PositionCard({ p, onClose, busy }: { p: Position; onClose: (p: Position) => void; busy: boolean }) {
  const r = rMultiple(p);
  const notional = p.entry_price * p.quantity;
  const toStop = stopDistancePct(p);
  return (
    <Card>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 }}>
        <Text style={[styles.text, { fontWeight: '600', fontSize: 16 }]}>
          #{p.id} {p.symbol}
        </Text>
        <Text style={{ color: p.side === 'long' ? colors.up : colors.down, fontWeight: '600' }}>
          {p.side.toUpperCase()}
        </Text>
      </View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 2 }}>
        <View>
          <Text style={styles.muted}>Gerçekleşmemiş PnL</Text>
          <Text style={{ color: pnlColor(p.unrealized_pnl), fontSize: 20, fontWeight: '700', fontVariant: ['tabular-nums'] }}>
            {signed(p.unrealized_pnl)}
            <Text style={{ fontSize: 12, fontWeight: '400' }}>
              {' '}
              {p.unrealized_pnl !== null && notional ? signedPct((p.unrealized_pnl / notional) * 100) : ''}
            </Text>
          </Text>
        </View>
        <View style={{ alignItems: 'flex-end' }}>
          <Text style={styles.muted}>R katı</Text>
          <Text style={{ color: pnlColor(r), fontSize: 16, fontWeight: '600', fontVariant: ['tabular-nums'] }}>
            {r === null ? '-' : `${r > 0 ? '+' : ''}${num(r, 2)}R`}
          </Text>
        </View>
      </View>
      <PriceRange p={p} />
      <View style={{ height: 6 }} />
      <Row label="Miktar" value={`${p.quantity} (${num(notional)})`} />
      <Row label="Giriş" value={price(p.entry_price)} />
      <Row label="Güncel fiyat" value={price(p.current_price)} />
      <Row label="Stop" value={`${price(p.stop_loss)}${toStop !== null ? ` · %${num(toStop)} uzakta` : ''}`} color={colors.down} />
      <Row label="Take profit" value={price(p.take_profit)} color={colors.up} />
      <Row label="Trailing stop" value={p.trailing_active ? price(p.trailing_stop) : 'henüz aktif değil'} />
      <Row label="Açılış" value={`${time(p.opened_at)} · ${between(p.opened_at)}`} />
      <View style={{ marginTop: 10 }}>
        <Button
          label={p.close_pending ? 'Kapatma kuyrukta' : 'Kapat'}
          tone="danger"
          disabled={p.close_pending}
          busy={busy}
          onPress={() => onClose(p)}
        />
      </View>
    </Card>
  );
}

export default function PositionsScreen() {
  const connection = useRequiredConnection();
  const { positions, status, refresh } = useLive();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const close = async (p: Position) => {
    setBusyId(p.id);
    try {
      const res = await api.closePosition(connection, p.id);
      setMessage(
        res.already_queued
          ? `#${p.id} için kapatma zaten kuyrukta.`
          : `#${p.id} kapatma komutu kuyruğa alındı; bot birkaç saniye içinde işleyecek.`,
      );
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const confirmClose = (p: Position) => {
    const title = `#${p.id} ${p.symbol} kapatılsın mı?`;
    if (Platform.OS === 'web') {
      // Alert.alert has no buttons on web
      if (globalThis.confirm?.(title)) close(p);
      return;
    }
    Alert.alert(title, 'Bot pozisyonu piyasa fiyatından kapatacak.', [
      { text: 'Vazgeç', style: 'cancel' },
      { text: 'Kapat', style: 'destructive', onPress: () => close(p) },
    ]);
  };

  return (
    <FlatList
      style={styles.screen}
      contentContainerStyle={styles.content}
      data={positions}
      keyExtractor={(p) => String(p.id)}
      renderItem={({ item }) => <PositionCard p={item} onClose={confirmClose} busy={busyId === item.id} />}
      ListHeaderComponent={
        <View style={{ gap: 8 }}>
          {message ? <Banner tone="info" text={message} /> : null}
          {status && !status.bot_running ? (
            <Banner text="Bot çalışmıyor: kapatma komutları bot yeniden başlayınca işlenir." />
          ) : null}
        </View>
      }
      ListEmptyComponent={<Empty text="Açık pozisyon yok." />}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={colors.accent}
          onRefresh={async () => {
            setRefreshing(true);
            await refresh();
            setRefreshing(false);
          }}
        />
      }
    />
  );
}
