import { Link, Redirect } from 'expo-router';
import { Tabs } from 'expo-router/js-tabs';
import { type ColorValue, Text } from 'react-native';

import { useConnection } from '../../lib/connection';
import { LiveProvider } from '../../lib/live';
import { colors } from '../../lib/theme';

function icon(glyph: string) {
  return ({ color }: { color: ColorValue }) => <Text style={{ color, fontSize: 16 }}>{glyph}</Text>;
}

export default function TabsLayout() {
  const { connection } = useConnection();
  if (!connection) return <Redirect href="/connect" />;

  return (
    <LiveProvider connection={connection}>
      <Tabs
        screenOptions={{
          tabBarActiveTintColor: colors.accent,
          tabBarInactiveTintColor: colors.muted,
          headerRight: () => (
            <Link href="/connect" style={{ color: colors.accent, marginRight: 12 }}>
              Bağlantı
            </Link>
          ),
        }}
      >
        <Tabs.Screen name="index" options={{ title: 'Özet', tabBarIcon: icon('◉') }} />
        <Tabs.Screen name="positions" options={{ title: 'Pozisyonlar', tabBarIcon: icon('▤') }} />
        <Tabs.Screen name="trades" options={{ title: 'İşlemler', tabBarIcon: icon('⇅') }} />
        <Tabs.Screen name="logs" options={{ title: 'Log', tabBarIcon: icon('≡') }} />
        <Tabs.Screen name="settings" options={{ title: 'Ayarlar', tabBarIcon: icon('⚙') }} />
      </Tabs>
    </LiveProvider>
  );
}
