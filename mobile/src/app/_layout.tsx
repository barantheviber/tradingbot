import { DarkTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { ActivityIndicator, View } from 'react-native';

import { ConnectionProvider, useConnection } from '../lib/connection';
import { colors } from '../lib/theme';

const theme = {
  ...DarkTheme,
  colors: { ...DarkTheme.colors, background: colors.bg, card: colors.card, border: colors.border, primary: colors.accent },
};

function Root() {
  const { ready } = useConnection();
  if (!ready) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg, justifyContent: 'center' }}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }
  return (
    <Stack screenOptions={{ contentStyle: { backgroundColor: colors.bg } }}>
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="connect" options={{ title: 'Bağlantı' }} />
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <ThemeProvider value={theme}>
      <ConnectionProvider>
        <StatusBar style="light" />
        <Root />
      </ConnectionProvider>
    </ThemeProvider>
  );
}
