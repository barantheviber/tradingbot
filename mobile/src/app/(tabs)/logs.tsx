import { useMemo, useState } from 'react';
import { FlatList, Pressable, ScrollView, Text, View } from 'react-native';

import { Empty, styles } from '../../components/ui';
import { useLive } from '../../lib/live';
import { colors } from '../../lib/theme';

const CATEGORIES = ['hepsi', 'trade', 'decision', 'signal', 'risk', 'trailing', 'error', 'lifecycle', 'settings', 'command'];

function levelColor(level: string): string {
  if (level === 'ERROR' || level === 'CRITICAL') return colors.down;
  if (level === 'WARNING') return colors.warn;
  return colors.muted;
}

export default function LogsScreen() {
  const { logs } = useLive();
  const [category, setCategory] = useState('hepsi');
  const shown = useMemo(() => (category === 'hepsi' ? logs : logs.filter((e) => e.category === category)), [logs, category]);

  return (
    <View style={styles.screen}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ padding: 8, gap: 6 }} style={{ flexGrow: 0 }}>
        {CATEGORIES.map((c) => (
          <Pressable
            key={c}
            onPress={() => setCategory(c)}
            style={{
              paddingHorizontal: 10,
              paddingVertical: 4,
              borderRadius: 12,
              borderWidth: 1,
              borderColor: c === category ? colors.accent : colors.border,
            }}
          >
            <Text style={{ color: c === category ? colors.accent : colors.muted, fontSize: 12 }}>{c}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <FlatList
        data={shown}
        keyExtractor={(e) => String(e.id)}
        contentContainerStyle={{ paddingHorizontal: 10, paddingBottom: 20 }}
        ListEmptyComponent={<Empty text="Log yok." />}
        renderItem={({ item: e }) => (
          <View style={{ paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border }}>
            <Text style={{ color: colors.muted, fontSize: 11, fontFamily: 'monospace' }}>
              {e.timestamp.replace('T', ' ').replace('+00:00', 'Z')}{' '}
              <Text style={{ color: levelColor(e.level) }}>{e.level}</Text> {e.category}
              {e.symbol ? ` ${e.symbol}` : ''}
            </Text>
            <Text style={{ color: colors.text, fontSize: 13, fontFamily: 'monospace' }}>{e.message}</Text>
          </View>
        )}
      />
    </View>
  );
}
