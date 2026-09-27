import * as SecureStore from 'expo-secure-store';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { normalizeBaseUrl, type Connection } from '../api/client';

// The token is stored in the OS keychain / keystore, never in plain storage.
const KEY_URL = 'tradingbot.baseUrl';
const KEY_TOKEN = 'tradingbot.token';

interface ConnectionState {
  ready: boolean; // finished reading secure storage
  connection: Connection | null;
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
  const [ready, setReady] = useState(false);
  const [connection, setConnection] = useState<Connection | null>(null);

  useEffect(() => {
    (async () => {
      try {
        if (await available()) {
          const [baseUrl, token] = await Promise.all([
            SecureStore.getItemAsync(KEY_URL),
            SecureStore.getItemAsync(KEY_TOKEN),
          ]);
          if (baseUrl && token) setConnection({ baseUrl, token });
        }
      } finally {
        setReady(true);
      }
    })();
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

  const value = useMemo(() => ({ ready, connection, save, clear }), [ready, connection, save, clear]);
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
