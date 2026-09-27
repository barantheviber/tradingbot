import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Text, TextInput, View } from 'react-native';

import { api, ApiError, normalizeBaseUrl } from '../api/client';
import { Banner, Button, Card, styles } from '../components/ui';
import { useConnection } from '../lib/connection';
import { colors } from '../lib/theme';

export default function ConnectScreen() {
  const { connection, save, clear } = useConnection();
  const [url, setUrl] = useState(connection?.baseUrl ?? 'http://192.168.1.10:8000');
  const [token, setToken] = useState(connection?.token ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const conn = { baseUrl: normalizeBaseUrl(url), token: token.trim() };
    try {
      const status = await api.status(conn); // verifies the address and the token
      await save(conn.baseUrl, conn.token);
      if (status) router.replace('/');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Card title="Bot sunucusu">
          <Text style={styles.muted}>
            Botun çalıştığı bilgisayarda `python -m api` çalışıyor olmalı. Adres ve token `.env` dosyasındaki
            API_HOST / API_PORT / API_TOKEN değerleridir.
          </Text>
          <View style={{ gap: 8, marginTop: 12 }}>
            <Text style={styles.text}>Adres</Text>
            <TextInput
              style={styles.input}
              value={url}
              onChangeText={setUrl}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              placeholder="http://100.x.y.z:8000"
              placeholderTextColor={colors.muted}
            />
            <Text style={styles.text}>API token</Text>
            <TextInput
              style={styles.input}
              value={token}
              onChangeText={setToken}
              autoCapitalize="none"
              autoCorrect={false}
              secureTextEntry
              placeholder="API_TOKEN"
              placeholderTextColor={colors.muted}
            />
            <Button label="Bağlan" tone="primary" onPress={submit} busy={busy} disabled={!url || !token} />
            {connection ? <Button label="Bağlantıyı sil" tone="danger" onPress={clear} /> : null}
          </View>
        </Card>
        {error ? <Banner tone="error" text={error} /> : null}
        <Banner
          tone="info"
          text="Trafik şifresiz HTTP'dir. Sunucuyu internete açmayın; aynı Wi-Fi ağında veya Tailscale gibi bir VPN üzerinden bağlanın."
        />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
