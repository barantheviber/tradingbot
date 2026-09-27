import * as SecureStore from 'expo-secure-store';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { BotRuntime } from '../../modules/bot-runtime';
import { normalizeBaseUrl, type Connection } from '../api/client';
import { LOCAL_BASE_URL, type LocalSetup } from './localSetup';

// The token is stored in the OS keychain / keystore, never in plain storage.
const KEY_URL = 'tradingbot.baseUrl';
const KEY_TOKEN = 'tradingbot.token';
const KEY_LOCAL_SETUP = 'tradingbot.localSetup';
const KEY_LOCAL_TOKEN = 'tradingbot.localToken';

interface ConnectionState {
  ready: boolean; // finished reading secure storage
  /** true in the installed Android app: the bot runs on this phone and the app talks to it on 127.0.0.1 */
  local: boolean;
  connection: Connection | null;
  /** local mode only */
  localSetup: LocalSetup | null;
  saveLocalSetup: (setup: LocalSetup) => Promise<Connection>;
  save: (baseUrl: string, token: string) => Promise<void>;
  clear: () => Promise<void>;
}

const Ctx = createContext<ConnectionState | null>(null);

async function available(): Promise<boolean> {
  try {
    return await SecureStore.isAvailableAsync();
  } catch {
    return false; // e.g. web: keep the connection in memory only
  }
}

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const local = BotRuntime !== null;
  const [ready, setReady] = useState(false);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [localSetup, setLocalSetup] = useState<LocalSetup | null>(null);

  useEffect(() => {
    (async () => {
      try {
        if (!(await available())) return;
        if (local) {
          const [setup, token] = await Promise.all([
            SecureStore.getItemAsync(KEY_LOCAL_SETUP),
            SecureStore.getItemAsync(KEY_LOCAL_TOKEN),
          ]);
          if (setup && token) {
            setLocalSetup(JSON.parse(setup) as LocalSetup);
            setConnection({ baseUrl: LOCAL_BASE_URL, token });
          }
          return;
        }
        const [baseUrl, token] = await Promise.all([
          SecureStore.getItemAsync(KEY_URL),
          SecureStore.getItemAsync(KEY_TOKEN),
        ]);
        if (baseUrl && token) setConnection({ baseUrl, token });
      } finally {
        setReady(true);
      }
    })();
  }, [local]);

  const saveLocalSetup = useCallback(async (setup: LocalSetup) => {
    let token = await SecureStore.getItemAsync(KEY_LOCAL_TOKEN);
    if (!token) {
      token = BotRuntime!.newToken();
      await SecureStore.setItemAsync(KEY_LOCAL_TOKEN, token);
    }
    await SecureStore.setItemAsync(KEY_LOCAL_SETUP, JSON.stringify(setup));
    const conn = { baseUrl: LOCAL_BASE_URL, token };
    setLocalSetup(setup);
    setConnection(conn);
    return conn;
  }, []);

  const save = useCallback(async (baseUrl: string, token: string) => {
    const conn = { baseUrl: normalizeBaseUrl(baseUrl), token: token.trim() };
    if (await available()) {
      await SecureStore.setItemAsync(KEY_URL, conn.baseUrl);
      await SecureStore.setItemAsync(KEY_TOKEN, conn.token);
    }
    setConnection(conn);
  }, []);

  const clear = useCallback(async () => {
    if (await available()) {
      await SecureStore.deleteItemAsync(KEY_URL);
      await SecureStore.deleteItemAsync(KEY_TOKEN);
    }
    setConnection(null);
  }, []);

  const value = useMemo(
    () => ({ ready, local, connection, localSetup, saveLocalSetup, save, clear }),
    [ready, local, connection, localSetup, saveLocalSetup, save, clear],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useConnection(): ConnectionState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useConnection must be used inside ConnectionProvider');
  return ctx;
}

/** For screens that only render once a connection exists (the tabs). */
export function useRequiredConnection(): Connection {
  const { connection } = useConnection();
  if (!connection) throw new Error('no connection configured');
  return connection;
}
