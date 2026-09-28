import Constants from 'expo-constants';
import * as SecureStore from 'expo-secure-store';
import { useEffect, useRef, useState } from 'react';
import { AppState, Linking, Platform, Text, View } from 'react-native';

import {
  createUpdateChecker,
  LATEST_RELEASE_API,
  releasePageUrl,
  releaseVersion,
  REQUEST_TIMEOUT_MS,
  UPDATE_TITLE,
  type UpdateInfo,
} from '../lib/updateCheck';
import { colors } from '../lib/theme';
import { Button, styles } from './ui';

const KEY = 'tradingbot.updateCheck';
// GitHub is asked at most once a day (lib/updateCheck.ts); asking this often only reads the saved answer.
const ASK_EVERY_MS = 60 * 60 * 1000;

async function fetchLatest(): Promise<unknown> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(LATEST_RELEASE_API, {
      headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'TradingBot-android' },
      signal: abort.signal,
    });
    if (!res.ok) throw new Error(`GitHub ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// Only the installed Android app checks: a development build has no release version to compare.
const installed = Constants.expoConfig?.version;
const checker =
  !__DEV__ && Platform.OS === 'android' && installed
    ? createUpdateChecker({
        current: installed,
        now: () => Date.now(),
        load: async () => {
          const raw = await SecureStore.getItemAsync(KEY);
          return raw ? JSON.parse(raw) : null;
        },
        save: (state) => SecureStore.setItemAsync(KEY, JSON.stringify(state)),
        fetchLatest,
      })
    : null;

/** "Yeni sürüm var": a newer release exists. It only opens the download page; it installs nothing. */
export function UpdateCard() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  // An answer that was on its way while "Kapat" was pressed must not bring the notice back.
  const closed = useRef<string | null>(null);

  useEffect(() => {
    if (!checker) return;
    let alive = true;
    const ask = () =>
      void checker
        .check()
        .then((u) => alive && setUpdate(u && u.version !== closed.current ? u : null))
        .catch(() => undefined);
    ask();
    const timer = setInterval(ask, ASK_EVERY_MS);
    const sub = AppState.addEventListener('change', (s) => s === 'active' && ask());
    return () => {
      alive = false;
      clearInterval(timer);
      sub.remove();
    };
  }, []);

  if (!update) return null;

  const open = () => {
    const v = releaseVersion(update.version);
    if (v) Linking.openURL(releasePageUrl(v)).catch(() => undefined);
  };
  const close = () => {
    closed.current = update.version;
    void checker?.dismiss(update.version);
    setUpdate(null);
  };

  return (
    <View style={[styles.card, { borderColor: colors.accent, gap: 6 }]}>
      <Text style={{ color: colors.accent, fontWeight: '600' }}>
        {UPDATE_TITLE}: v{update.version}
      </Text>
      <Text style={styles.muted}>
        İndirme sayfasından yeni .apk dosyasını indirip kurun. Eskisinin üstüne kurulur; ayarlarınız ve paper geçmişiniz
        korunur, çalışan bot güncellemeden sonra kendiliğinden devam eder.
      </Text>
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <View style={{ flex: 1 }}>
          <Button label="İndirme sayfasını aç" tone="primary" onPress={open} />
        </View>
        <View style={{ flex: 1 }}>
          <Button label="Kapat" onPress={close} />
        </View>
      </View>
    </View>
  );
}
