import Constants from 'expo-constants';
import * as SecureStore from 'expo-secure-store';
import { useEffect, useState } from 'react';
import { AppState, Linking, Platform, Text, View } from 'react-native';

import {
  checkForUpdate,
  cleanState,
  dismissedState,
  LATEST_RELEASE_API,
  releasePageUrl,
  releaseVersion,
  REQUEST_TIMEOUT_MS,
  UPDATE_TITLE,
  type UpdateCheckState,
  type UpdateInfo,
} from '../lib/updateCheck';
import { colors } from '../lib/theme';
import { Button, styles } from './ui';

const KEY = 'tradingbot.updateCheck';
// GitHub is asked at most once a day (lib/updateCheck.ts); asking this often only reads the saved answer.
const ASK_EVERY_MS = 60 * 60 * 1000;

async function load(): Promise<unknown> {
  const raw = await SecureStore.getItemAsync(KEY);
  return raw ? JSON.parse(raw) : null;
}

async function save(state: UpdateCheckState): Promise<void> {
  await SecureStore.setItemAsync(KEY, JSON.stringify(state));
}

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

// One check at a time, so the screen and the app coming back to the front never send two requests.
let checking: Promise<UpdateInfo | null> | null = null;

function availableUpdate(): Promise<UpdateInfo | null> {
  // Only the installed Android app: a development build has no release version to compare.
  const current = Constants.expoConfig?.version;
  if (__DEV__ || Platform.OS !== 'android' || !current) return Promise.resolve(null);
  checking ??= checkForUpdate({ current, now: Date.now, load, save, fetchLatest }).finally(() => {
    checking = null;
  });
  return checking;
}

async function dismiss(version: string): Promise<void> {
  await checking; // a check still writing would otherwise put the closed notice back
  let state: UpdateCheckState;
  try {
    state = cleanState(await load());
  } catch {
    state = cleanState(null);
  }
  await save(dismissedState(state, version)).catch(() => undefined);
}

/** "Yeni sürüm var": a newer release exists. It only opens the download page; it installs nothing. */
export function UpdateCard() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);

  useEffect(() => {
    let alive = true;
    const ask = () =>
      void availableUpdate()
        .then((u) => alive && setUpdate(u))
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
    void dismiss(update.version);
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
