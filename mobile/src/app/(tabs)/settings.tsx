import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { FlatList, RefreshControl, Switch, Text, TextInput, View } from 'react-native';

import { api } from '../../api/client';
import type { Setting, SettingValue } from '../../api/types';
import { Banner, Button, styles } from '../../components/ui';
import { useRequiredConnection } from '../../lib/connection';
import { settingLabel } from '../../lib/settingLabels';
import { colors } from '../../lib/theme';

function SettingRow({ setting, onSave }: { setting: Setting; onSave: (key: string, value: SettingValue) => Promise<string | null> }) {
  const [draft, setDraft] = useState(String(setting.value));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = setting.type !== 'bool' && draft !== String(setting.value);

  const save = async (value: SettingValue) => {
    setBusy(true);
    setError(await onSave(setting.key, value));
    setBusy(false);
  };

  return (
    <View style={[styles.card, { gap: 6 }]}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text style={[styles.text, { fontWeight: '600', flexShrink: 1 }]}>{settingLabel(setting.key)}</Text>
        {setting.type === 'bool' ? (
          <Switch value={Boolean(setting.value)} disabled={busy} onValueChange={(v) => save(v)} />
        ) : null}
      </View>
      <Text style={styles.muted}>{setting.description}</Text>
      {setting.type !== 'bool' ? (
        <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
          <TextInput
            style={[styles.input, { flex: 1 }]}
            value={draft}
            onChangeText={setDraft}
            keyboardType={setting.type === 'str' ? 'default' : 'decimal-pad'}
            autoCapitalize="none"
            autoCorrect={false}
          />
          <Button label="Kaydet" tone="primary" disabled={!dirty} busy={busy} onPress={() => save(draft.replace(',', '.'))} />
        </View>
      ) : null}
      {error ? <Text style={{ color: colors.down, fontSize: 12 }}>{error}</Text> : null}
    </View>
  );
}

export default function SettingsScreen() {
  const connection = useRequiredConnection();
  const [settings, setSettings] = useState<Setting[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setSettings(await api.settings(connection));
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

  // Returns an error message for the row, or null on success. The server validates and coerces the value.
  const save = useCallback(
    async (key: string, value: SettingValue) => {
      try {
        const res = await api.updateSetting(connection, key, value);
        setSettings((cur) => cur.map((s) => (s.key === key ? { ...s, value: res.value } : s)));
        return null;
      } catch (e) {
        return e instanceof Error ? e.message : String(e);
      }
    },
    [connection],
  );

  return (
    <FlatList
      style={styles.screen}
      contentContainerStyle={styles.content}
      data={settings}
      keyExtractor={(s) => `${s.key}:${String(s.value)}`}
      renderItem={({ item }) => <SettingRow setting={item} onSave={save} />}
      ListHeaderComponent={
        <View style={{ gap: 8 }}>
          {error ? <Banner tone="error" text={error} /> : null}
          <Text style={styles.muted}>
            Değişiklikler botun veritabanına yazılır; bot bir sonraki kapanmış mumda yeni değerleri kullanır. Paper/live
            modu ve API anahtarları buradan değiştirilemez.
          </Text>
        </View>
      }
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
    />
  );
}
