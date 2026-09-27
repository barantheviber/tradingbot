import { useState } from "react";
import { api } from "../api";
import { pnlClass, price, signed, time } from "../format";
import { usePolling } from "../usePolling";

export default function Trades() {
  const [limit, setLimit] = useState(200);
  const trades = usePolling(() => api.trades(limit), 30_000, [limit]);

  return (
    <div className="card">
      <div className="card-head">
        <h3>İşlem geçmişi</h3>
        <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
          {[50, 200, 500, 1000].map((n) => (
            <option key={n} value={n}>
              Son {n}
            </option>
          ))}
        </select>
        <button onClick={() => void trades.refresh()}>Yenile</button>
        {trades.error && <span className="error-inline">{trades.error}</span>}
      </div>
      {!trades.data?.length ? (
        <p className="empty">{trades.loading ? "Yükleniyor…" : "İşlem yok."}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Açılış</th>
              <th>Kapanış</th>
              <th>Sembol</th>
              <th>Yön</th>
              <th className="r">Miktar</th>
              <th className="r">Giriş</th>
              <th className="r">Çıkış</th>
              <th className="r">Komisyon</th>
              <th className="r">PnL</th>
              <th>Sebep</th>
            </tr>
          </thead>
          <tbody>
            {trades.data.map((t) => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>{time(t.opened_at)}</td>
                <td>{time(t.closed_at)}</td>
                <td>{t.symbol}</td>
                <td className={t.side === "long" ? "pos" : "neg"}>{t.side === "long" ? "LONG" : "SHORT"}</td>
                <td className="r">{t.quantity}</td>
                <td className="r">{price(t.entry_price)}</td>
                <td className="r">{price(t.exit_price)}</td>
                <td className="r">{price(t.fees)}</td>
                <td className={`r ${pnlClass(t.pnl)}`}>{signed(t.pnl)}</td>
                <td>{reason(t.exit_reason)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const REASONS: Record<string, string> = {
  stop_loss: "Stop",
  take_profit: "Kâr al",
  trailing_stop: "Trailing stop",
  manual: "Elle kapatıldı",
};

function reason(r: string | null): string {
  return r ? REASONS[r] ?? r : "";
}
