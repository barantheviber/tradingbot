import { useState } from 'react';
import { Alert, Text, View } from 'react-native';

import { api, type Connection } from '../api/client';
import type { SafetyHalt } from '../api/types';
import { SAFETY_HALT_HINT, SAFETY_HALT_TITLE, safetyHaltReason } from '../lib/safetyHalt';
import { colors } from '../lib/theme';
import { Button, styles } from './ui';

/** Shown on the overview while the automatic brake keeps the bot from opening new positions. */
export function SafetyHaltCard({ halt, connection, onChanged }: { halt: SafetyHalt; connection: Connection; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!halt.active) return null;

  const release = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.updateSetting(connection, 'safety_halt_active', false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const ask = () =>
    Alert.alert('Fren kaldırılsın mı?', 'Bot yeniden yeni pozisyon açabilir; zirve ve zarar serisi sıfırlanır.', [
      { text: 'Vazgeç', style: 'cancel' },
      { text: 'Freni kaldır', onPress: () => void release() },
    ]);

  return (
    <View style={[styles.card, { borderColor: colors.down, gap: 6 }]}>
      <Text style={{ color: colors.down, fontWeight: '600' }}>{SAFETY_HALT_TITLE}</Text>
      <Text style={styles.text}>{safetyHaltReason(halt)}</Text>
      <Text style={styles.muted}>{SAFETY_HALT_HINT}</Text>
      {error ? <Text style={{ color: colors.down, fontSize: 12 }}>{error}</Text> : null}
      <Button label="Freni kaldır" tone="primary" onPress={ask} busy={busy} />
    </View>
  );
}
