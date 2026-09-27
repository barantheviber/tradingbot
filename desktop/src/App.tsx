import { useCallback, useEffect, useState } from "react";
import type { BotStatus, ConnectionConfig, LogLine, Position, WsState } from "../shared/types";
import { api } from "./api";
import StatusBar from "./components/StatusBar";
import Connection from "./views/Connection";
import Logs from "./views/Logs";
import Overview from "./views/Overview";
import Settings from "./views/Settings";
import Trades from "./views/Trades";

type Tab = "overview" | "trades" | "settings" | "logs" | "connection";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Genel bakış" },
  { id: "trades", label: "İşlem geçmişi" },
  { id: "settings", label: "Strateji ayarları" },
  { id: "logs", label: "Loglar" },
  { id: "connection", label: "Bağlantı" },
];

const MAX_LOGS = 1000;
// Polling keeps the app current when the WebSocket is down; with it open, polling is slower.
const POLL_WS_OPEN_MS = 30_000;
const POLL_WS_CLOSED_MS = 5_000;

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [config, setConfig] = useState<ConnectionConfig | null>(null);
  const [wsState, setWsState] = useState<WsState>("closed");
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([api.status(), api.positions()]);
      setStatus(s);
      setPositions(p);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const refreshLogs = useCallback(async () => {
    try {
      setLogs((await api.logs(300)).slice(-MAX_LOGS));
    } catch {
      // the status error already tells the user the bot is unreachable
    }
  }, []);

  useEffect(() => {
    void window.desktop.getConfig().then(setConfig);
    const offState = window.desktop.onWsState(setWsState);
    void window.desktop.getWsState().then(setWsState);
    const offEvent = window.desktop.onEvent((ev) => {
      if (ev.type === "status") setStatus(ev.data);
      else if (ev.type === "positions") setPositions(ev.data);
      else if (ev.type === "log")
        setLogs((prev) => (prev.some((l) => l.id === ev.data.id) ? prev : [...prev, ev.data].slice(-MAX_LOGS)));
    });
    return () => {
      offState();
      offEvent();
    };
  }, []);

  useEffect(() => {
    if (!config) return;
    void refresh();
    void refreshLogs();
    const t = setInterval(() => {
      void refresh();
      if (wsState !== "open") void refreshLogs();
    }, wsState === "open" ? POLL_WS_OPEN_MS : POLL_WS_CLOSED_MS);
    return () => clearInterval(t);
  }, [config, wsState, refresh, refreshLogs]);

  useEffect(() => {
    if (config && !config.hasToken) setTab("connection");
  }, [config]);

  return (
    <div className="app">
      <StatusBar status={status} wsState={wsState} error={error} />
      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={t.id === tab ? "tab active" : "tab"} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      <main className="content">
        {tab === "overview" && <Overview status={status} positions={positions} onChanged={refresh} />}
        {tab === "trades" && <Trades />}
        {tab === "settings" && <Settings />}
        {tab === "logs" && <Logs logs={logs} onRefresh={refreshLogs} />}
        {tab === "connection" && config && (
          <Connection
            config={config}
            onSaved={(c) => {
              setConfig(c);
              void refresh();
              void refreshLogs();
            }}
          />
        )}
      </main>
    </div>
  );
}
