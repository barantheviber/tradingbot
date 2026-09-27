import { useState } from 'react';
import { Alert, FlatList, Platform, RefreshControl, Text, View } from 'react-native';

import { api } from '../../api/client';
import type { Position } from '../../api/types';
import { Banner, Button, Card, Empty, Row, styles } from '../../components/ui';
import { useRequiredConnection } from '../../lib/connection';
import { price, signed, time } from '../../lib/format';
import { useLive } from '../../lib/live';
import { colors, pnlColor } from '../../lib/theme';

function PositionCard({ p, onClose, busy }: { p: Position; onClose: (p: Position) => void; busy: boolean }) {
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
      <Row label="Miktar" value={String(p.quantity)} />
      <Row label="Giriş" value={price(p.entry_price)} />
      <Row label="Güncel fiyat" value={price(p.current_price)} />
      <Row label="Stop" value={price(p.stop_loss)} color={colors.down} />
      <Row label="Take profit" value={price(p.take_profit)} color={colors.up} />
      <Row label="Trailing stop" value={p.trailing_active ? price(p.trailing_stop) : 'henüz aktif değil'} />
      <Row label="Gerçekleşmemiş PnL" value={signed(p.unrealized_pnl)} color={pnlColor(p.unrealized_pnl)} />
      <Row label="Açılış" value={time(p.opened_at)} />
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
