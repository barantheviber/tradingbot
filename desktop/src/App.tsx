import { useCallback, useEffect, useState } from "react";
import type { ConnectionConfig, LocalBotState, LocalSetup, LogEvent, Position, Status, WsState } from "../shared/types";
import { api } from "./api";
import BotControl from "./components/BotControl";
import StatusBar from "./components/StatusBar";
import Connection from "./views/Connection";
import Logs from "./views/Logs";
import Overview from "./views/Overview";
import Settings from "./views/Settings";
import Setup from "./views/Setup";
import Trades from "./views/Trades";

type Tab = "overview" | "trades" | "settings" | "logs" | "setup" | "connection";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Genel bakış" },
  { id: "trades", label: "İşlem geçmişi" },
  { id: "settings", label: "Strateji ayarları" },
  { id: "logs", label: "Loglar" },
];
// The bot runs inside the app; "Bağlantı" only exists when developing against an external API.
const SETUP_TAB = { id: "setup" as const, label: "Kurulum" };
const CONNECTION_TAB = { id: "connection" as const, label: "Bağlantı" };

const MAX_LOGS = 1000;
// Polling keeps the app current when the WebSocket is down; with it open, polling is slower.
const POLL_WS_OPEN_MS = 30_000;
const POLL_WS_CLOSED_MS = 5_000;

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [config, setConfig] = useState<ConnectionConfig | null>(null);
  const [wsState, setWsState] = useState<WsState>("closed");
  const [status, setStatus] = useState<Status | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [local, setLocal] = useState<LocalBotState | null>(null);
  const [setup, setSetup] = useState<LocalSetup | null>(null);

  const loadLocal = useCallback(async () => {
    const [s, cfg] = await Promise.all([window.desktop.localBot.getState(), window.desktop.localBot.getSetup()]);
    setLocal(s);
    setSetup(cfg);
    setConfig(await window.desktop.getConfig());
  }, []);

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
    void loadLocal();
    const offLocal = window.desktop.localBot.onState(setLocal);
    const offState = window.desktop.onWsState(setWsState);
    void window.desktop.getWsState().then(setWsState);
    const offEvent = window.desktop.onEvent((ev) => {
      if (ev.type === "status") setStatus(ev.data);
      else if (ev.type === "positions") setPositions(ev.data);
      else if (ev.type === "logs")
        setLogs((prev) => {
          // pushes arrive newest first; keep the list oldest first without duplicates
          const seen = new Set(prev.map((l) => l.id));
          const fresh = ev.data.filter((l) => !seen.has(l.id)).reverse();
          return fresh.length ? [...prev, ...fresh].slice(-MAX_LOGS) : prev;
        });
    });
    return () => {
      offLocal();
      offState();
      offEvent();
    };
  }, [loadLocal]);

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
    if (local && !local.managed && config && !config.hasToken) setTab("connection");
  }, [config, local]);

  if (!local) return null;
  if (local.managed && !local.setupDone) {
    return (
      <div className="app">
        <main className="content">
          <Setup initial={null} firstRun botRunning={false} onSaved={() => void loadLocal()} />
        </main>
      </div>
    );
  }

  const tabs = [...TABS, local.managed ? SETUP_TAB : CONNECTION_TAB];
  const botUp = local.phase === "running";

  return (
    <div className="app">
      <StatusBar status={status} wsState={wsState} error={local.managed && !botUp ? null : error} />
      {local.managed && <BotControl state={local} positions={positions} onChanged={refresh} />}
      <nav className="tabs">
        {tabs.map((t) => (
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
        {tab === "setup" && (
          <Setup initial={setup} firstRun={false} botRunning={botUp} onSaved={() => void loadLocal()} />
        )}
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
