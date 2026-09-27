import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { FlatList, RefreshControl, Text, View } from 'react-native';

import { api } from '../../api/client';
import type { Trade } from '../../api/types';
import { Banner, Empty, styles } from '../../components/ui';
import { useRequiredConnection } from '../../lib/connection';
import { price, signed, time } from '../../lib/format';
import { colors, pnlColor } from '../../lib/theme';

export default function TradesScreen() {
  const connection = useRequiredConnection();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setTrades(await api.trades(connection, 200));
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

  return (
    <FlatList
      style={styles.screen}
      contentContainerStyle={styles.content}
      data={trades}
      keyExtractor={(t) => String(t.id)}
      ListHeaderComponent={error ? <Banner tone="error" text={error} /> : null}
      ListEmptyComponent={<Empty text="Henüz kapanmış işlem yok." />}
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
      renderItem={({ item: t }) => (
        <View style={[styles.card, { paddingVertical: 10 }]}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <Text style={[styles.text, { fontWeight: '600' }]}>
              #{t.id} {t.symbol} <Text style={{ color: t.side === 'long' ? colors.up : colors.down }}>{t.side}</Text>
            </Text>
            <Text style={{ color: pnlColor(t.pnl), fontWeight: '600' }}>{signed(t.pnl)}</Text>
          </View>
          <Text style={styles.muted}>
            {price(t.entry_price)} → {price(t.exit_price)} · {t.exit_reason ?? '-'} · {time(t.closed_at)}
          </Text>
        </View>
      )}
    />
  );
}
