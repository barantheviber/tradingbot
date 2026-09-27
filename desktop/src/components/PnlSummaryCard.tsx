import type { PnlSummary } from "../../shared/types";
import { num, pnlClass, signed } from "../format";

interface Props {
  summary: PnlSummary | null;
  error: string | null;
}

export default function PnlSummaryCard({ summary: s, error }: Props) {
  return (
    <div className="card">
      <div className="card-head">
        <h3>Performans özeti</h3>
        {error && <span className="error-inline">{error}</span>}
      </div>
      {s ? (
        <div className="stats">
          <Stat label="Toplam PnL" value={signed(s.total_pnl)} cls={pnlClass(s.total_pnl)} />
          <Stat label="İşlem" value={String(s.trades)} />
          <Stat label="Kazanma oranı" value={`%${num(s.win_rate_pct, 1)}`} />
          <Stat label="Profit factor" value={s.profit_factor === null ? "∞" : num(s.profit_factor)} />
          <Stat label="Ort. kazanç" value={num(s.avg_win)} cls="pos" />
          <Stat label="Ort. kayıp" value={num(s.avg_loss)} cls="neg" />
          <Stat label="Beklenti" value={signed(s.expectancy)} cls={pnlClass(s.expectancy)} />
          <Stat label="Maks. düşüş" value={`${num(s.max_drawdown)} (%${num(s.max_drawdown_pct)})`} cls="neg" />
          <Stat label="Komisyon" value={num(s.fees)} />
        </div>
      ) : (
        <p className="empty">Veri yok.</p>
      )}
    </div>
  );
}

function Stat({ label, value, cls = "" }: { label: string; value: string; cls?: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value ${cls}`}>{value}</span>
    </div>
  );
}
