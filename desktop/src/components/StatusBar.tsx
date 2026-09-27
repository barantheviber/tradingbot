import type { BotStatus, WsState } from "../../shared/types";
import { num, pnlClass, signed, time } from "../format";

interface Props {
  status: BotStatus | null;
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
          <span className={`badge ${status.running ? "badge-ok" : "badge-bad"}`}>
            {status.running ? "Çalışıyor" : "Durdu"}
          </span>
          {status.entries_halted && (
            <span className="badge badge-bad" title="Günlük zarar limiti aşıldı; UTC gece yarısına kadar yeni giriş yok">
              Yeni girişler durduruldu
            </span>
          )}
          <span className="meta">
            {status.exchange} · {status.symbols.join(", ")} · {status.timeframe}
          </span>
          <span className="meta">
            Bugünkü PnL <b className={pnlClass(status.today_pnl)}>{signed(status.today_pnl)}</b>
          </span>
          {status.equity !== undefined && <span className="meta">Özsermaye <b>{num(status.equity)}</b></span>}
          {status.last_candle_at && <span className="meta">Son mum {time(status.last_candle_at)}</span>}
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
