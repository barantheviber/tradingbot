import { useEffect, useState } from 'react';
import { Alert, Text, View } from 'react-native';

import { api, type Connection } from '../api/client';
import type { Position } from '../api/types';
import { useConnection } from '../lib/connection';
import { askBatteryUnrestricted, batteryUnrestricted, useLocalBot } from '../lib/localBot';
import { nextDecisionText } from '../lib/localSetup';
import { colors } from '../lib/theme';
import { Banner, Button, Card, styles } from './ui';

const LABEL = {
  stopped: 'Bot durdu',
  starting: 'Bot başlıyor…',
  running: 'Bot bu telefonda çalışıyor',
  stopping: 'Bot duruyor…',
  error: 'Bot durdu (hata)',
} as const;

async function waitForCommand(conn: Connection, id: number): Promise<boolean> {
  const until = Date.now() + 90_000;
  while (Date.now() < until) {
    await new Promise((r) => setTimeout(r, 2_000));
    try {
      const cmd = await api.command(conn, id);
      if (cmd.status !== 'pending') return cmd.status === 'done';
    } catch {
      // keep trying until the deadline
    }
  }
  return false;
}

/** Start/stop for the bot on this phone. Stopping with open positions asks what to do first. */
export function BotControl({ positions }: { positions: Position[] }) {
  const { connection, localSetup } = useConnection();
  const bot = useLocalBot();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [battery, setBattery] = useState(batteryUnrestricted);
  const phase = bot.state.phase;
  const active = phase === 'running' || phase === 'starting';
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const next = phase === 'running' && localSetup ? nextDecisionText(localSetup.timeframe, now) : null;

  const start = async () => {
    if (!localSetup || !connection) return;
    setError(null);
    await bot.start(localSetup, connection.token);
    if (!batteryUnrestricted()) {
      Alert.alert(
        'Pil ayarı',
        'Android arka plandaki uygulamaları kapatabilir. Botun kesintisiz çalışması için bir sonraki ekranda "İzin ver" deyin (Pil: Kısıtlanmamış).',
        [{ text: 'Sonra' }, { text: 'Ayarı aç', onPress: askBatteryUnrestricted }],
      );
    }
  };

  const closeAllThenStop = async () => {
    if (!connection) return;
    setError(null);
    setBusy(`${positions.length} pozisyon kapatılıyor…`);
    try {
      const queued = await Promise.all(positions.map((p) => api.closePosition(connection, p.id)));
      const results = await Promise.all(queued.map((q) => waitForCommand(connection, q.command_id)));
      const failed = results.filter((ok) => !ok).length;
      if (failed > 0) {
        setError(`${failed} pozisyon kapatılamadı; bot çalışmaya devam ediyor. Log sekmesine bakın.`);
        return;
      }
      bot.stop();
    } catch (e) {
      setError(`Kapatma komutu gönderilemedi: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const stop = () => {
    if (positions.length === 0) {
      bot.stop();
      return;
    }
    Alert.alert(
      `${positions.length} açık pozisyon var`,
      'Bot durunca bu pozisyonların stop-loss, kâr al ve trailing takibi de durur. Bot bu telefonda tekrar başlayınca kaldığı yerden devam eder, ama bilgisayardaki bot bu pozisyonları bilmez. Bilgisayara geçecekseniz önce pozisyonları kapatın.',
      [
        { text: 'Vazgeç', style: 'cancel' },
        { text: 'Sadece durdur', style: 'destructive', onPress: () => bot.stop() },
        { text: 'Kapat ve durdur', onPress: () => void closeAllThenStop() },
      ],
    );
  };

  return (
    <Card title="Bot">
      <Text style={{ color: phase === 'running' ? colors.up : phase === 'error' ? colors.down : colors.text, fontWeight: '600' }}>
        {busy ?? LABEL[phase]}
      </Text>
      {!busy && next ? <Text style={[styles.muted, { marginTop: 4 }]}>{next}. Arada işlem olmaması normaldir.</Text> : null}
      {bot.state.message ? <Text style={[styles.muted, { marginTop: 4 }]}>{bot.state.message}</Text> : null}
      {error ? <Text style={{ color: colors.down, marginTop: 4 }}>{error}</Text> : null}
      <View style={{ marginTop: 10, gap: 8 }}>
        {active ? (
          <Button label="Durdur" tone="danger" onPress={stop} busy={Boolean(busy)} />
        ) : (
          <Button label="Başlat" tone="primary" onPress={() => void start()} disabled={phase === 'stopping'} busy={Boolean(busy)} />
        )}
        {active && !battery ? (
          <>
            <Banner text='Pil optimizasyonu açık: Android botu arka planda durdurabilir. "Pil ayarını aç" ile Kısıtlanmamış yapın.' />
            <Button
              label="Pil ayarını aç"
              onPress={() => {
                askBatteryUnrestricted();
                setTimeout(() => setBattery(batteryUnrestricted()), 5_000);
              }}
            />
          </>
        ) : null}
      </View>
    </Card>
  );
}
