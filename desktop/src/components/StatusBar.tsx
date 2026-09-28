import type { Status, WsState } from "../../shared/types";
import { num, pnlClass, signed } from "../format";

interface Props {
  status: Status | null;
  wsState: WsState;
  error: string | null;
}

const WS_LABEL: Record<WsState, string> = { open: "Anlık akış", connecting: "Bağlanıyor", closed: "Akış yok" };

export default function StatusBar({ status, wsState, error }: Props) {
  return (
    <header className="statusbar">
      <div className="brand">Trading Bot</div>
      {status ? (
        <>
          <span className={`badge ${status.mode === "live" ? "badge-live" : "badge-paper"}`}>
            {status.mode === "live" ? "CANLI" : "PAPER"}
          </span>
          {status.testnet && <span className="badge badge-paper">TESTNET</span>}
          <span
            className={`badge ${status.bot_running ? "badge-ok" : "badge-bad"}`}
            title={heartbeat(status.heartbeat_age_sec)}
          >
            {status.bot_running ? "Çalışıyor" : "Durdu"}
          </span>
          {!status.trading_enabled && (
            <span className="badge badge-bad" title="trading_enabled ayarı kapalı; bot yeni pozisyon açmıyor">
              Yeni girişler kapalı
            </span>
          )}
          {status.safety_halt?.active && (
            <span className="badge badge-bad" title="Otomatik fren: yeni pozisyon açılmıyor">
              Otomatik fren
            </span>
          )}
          {status.entries_halted_by_daily_limit && (
            <span
              className="badge badge-bad"
              title={`Günlük zarar %${num(status.daily_loss_pct)} (limit %${num(status.daily_loss_limit_pct)}); UTC gece yarısına kadar yeni giriş yok`}
            >
              Yeni girişler durduruldu
            </span>
          )}
          <span className="meta">
            {status.exchange} · {status.symbols.join(", ")} · {status.timeframe}
          </span>
          <span className="meta">
            Bugünkü PnL <b className={pnlClass(status.today_pnl)}>{signed(status.today_pnl)}</b>
          </span>
          {status.equity !== null && <span className="meta">Özsermaye <b>{num(status.equity)}</b></span>}
          <span className="meta">
            Pozisyon {status.open_positions}
            {status.max_open_positions !== null ? `/${status.max_open_positions}` : ""}
          </span>
        </>
      ) : (
        <span className="meta">Durum bilinmiyor</span>
      )}
      <span className="spacer" />
      {error && <span className="error-inline" title={error}>{error}</span>}
      <span className={`dot dot-${wsState}`} title={WS_LABEL[wsState]} />
      <span className="meta">{WS_LABEL[wsState]}</span>
    </header>
  );
}

function heartbeat(age: number | null): string {
  if (age === null) return "Bottan hiç sinyal alınmadı";
  return `Son sinyal ${Math.round(age)} sn önce`;
}
