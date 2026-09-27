import { useEffect, useRef, useState } from "react";
import type { LogEvent } from "../../shared/types";
import { time } from "../format";

interface Props {
  logs: LogEvent[];
  onRefresh: () => void;
  /** the bot runs inside this app, so its log files are on this computer */
  canOpenFolder?: boolean;
}

const LEVELS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"];
const LEVEL_TR: Record<string, string> = {
  ALL: "Tümü",
  DEBUG: "Ayrıntı",
  INFO: "Bilgi",
  WARNING: "Uyarı",
  ERROR: "Hata",
  CRITICAL: "Kritik",
};
const levelTr = (l: string) => LEVEL_TR[l.toUpperCase()] ?? l;

export default function Logs({ logs, onRefresh, canOpenFolder = false }: Props) {
  const [level, setLevel] = useState("ALL");
  const [query, setQuery] = useState("");
  const [follow, setFollow] = useState(true);
  const end = useRef<HTMLDivElement>(null);

  const q = query.toLowerCase();
  const shown = logs.filter(
    (l) =>
      (level === "ALL" || l.level.toUpperCase() === level) &&
      (!q || l.message.toLowerCase().includes(q) || l.category.toLowerCase().includes(q) || (l.symbol ?? "").toLowerCase().includes(q)),
  );

  useEffect(() => {
    if (follow) end.current?.scrollIntoView({ block: "end" });
  }, [shown.length, follow]);

  return (
    <div className="card logs-card">
      <div className="card-head">
        <h3>Karar ve olay logları</h3>
        <select value={level} onChange={(e) => setLevel(e.target.value)}>
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {levelTr(l)}
            </option>
          ))}
        </select>
        <input placeholder="Filtrele…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <label className="switch">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          <span>Otomatik kaydır</span>
        </label>
        <button onClick={onRefresh}>Yenile</button>
        {canOpenFolder && (
          <button onClick={() => void window.desktop.localBot.openLogFolder()} title="Ayrıntılı log dosyaları">
            Log klasörünü aç
          </button>
        )}
      </div>
      <div className="terminal">
        {shown.map((l) => (
          <div key={l.id} className={`log log-${l.level.toLowerCase()}`}>
            <span className="log-time">{time(l.timestamp)}</span>
            <span className="log-level">{levelTr(l.level)}</span>
            <span className="log-cat">{l.category}</span>
            {l.symbol && <span className="log-sym">{l.symbol}</span>}
            <span className="log-msg">{l.message}</span>
          </div>
        ))}
        {!shown.length && <div className="empty">Log yok.</div>}
        <div ref={end} />
      </div>
    </div>
  );
}
