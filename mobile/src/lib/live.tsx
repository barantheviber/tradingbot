import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AppState } from 'react-native';

import { api, wsUrl, type Connection } from '../api/client';
import type { LogEvent, Position, Status, WsMessage } from '../api/types';

const MAX_LOGS = 300;
const MAX_BACKOFF_MS = 30_000;

interface LiveState {
  status: Status | null;
  positions: Position[];
  logs: LogEvent[]; // newest first
  wsConnected: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const Ctx = createContext<LiveState | null>(null);

function mergeLogs(incoming: LogEvent[], current: LogEvent[]): LogEvent[] {
  const seen = new Set(current.map((e) => e.id));
  const fresh = incoming.filter((e) => !seen.has(e.id));
  return [...fresh, ...current].sort((a, b) => b.id - a.id).slice(0, MAX_LOGS);
}

/**
 * Keeps status, positions and the log tail live over the API's WebSocket,
 * reconnecting with backoff and pausing while the app is in the background.
 */
export function LiveProvider({ connection, children }: { connection: Connection; children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(AppState.currentState === 'active');
  const backoff = useRef(1000);

  const refresh = useCallback(async () => {
    try {
      const [s, p, l] = await Promise.all([api.status(connection), api.positions(connection), api.logs(connection, 200)]);
      setStatus(s);
      setPositions(p);
      setLogs((cur) => mergeLogs(l, cur));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [connection]);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (s) => setActive(s === 'active'));
    return () => sub.remove();
  }, []);

  useEffect(() => {
    setStatus(null);
    setPositions([]);
    setLogs([]);
  }, [connection]);

  useEffect(() => {
    if (!active) return;
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const open = () => {
      ws = new WebSocket(wsUrl(connection));
      ws.onopen = () => {
        backoff.current = 1000;
        setWsConnected(true);
        setError(null);
      };
      ws.onmessage = (ev) => {
        let msg: WsMessage;
        try {
          msg = JSON.parse(String(ev.data)) as WsMessage;
        } catch {
          return;
        }
        if (msg.type === 'status') setStatus(msg.data);
        else if (msg.type === 'positions') setPositions(msg.data);
        else if (msg.type === 'logs') setLogs((cur) => mergeLogs(msg.data, cur));
      };
      ws.onclose = () => {
        setWsConnected(false);
        if (closed) return;
        timer = setTimeout(open, backoff.current);
        backoff.current = Math.min(backoff.current * 2, MAX_BACKOFF_MS);
      };
      ws.onerror = () => setError('Canlı bağlantı kurulamadı, tekrar deneniyor');
    };

    refresh();
    open();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
      setWsConnected(false);
    };
  }, [connection, active, refresh]);

  const value = useMemo(
    () => ({ status, positions, logs, wsConnected, error, refresh }),
    [status, positions, logs, wsConnected, error, refresh],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLive(): LiveState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useLive must be used inside LiveProvider');
  return ctx;
}
