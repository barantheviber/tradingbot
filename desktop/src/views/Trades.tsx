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
              <th>Zaman</th>
              <th>Poz.</th>
              <th>Sembol</th>
              <th>İşlem</th>
              <th>Yön</th>
              <th className="r">Miktar</th>
              <th className="r">Fiyat</th>
              <th className="r">Komisyon</th>
              <th className="r">PnL</th>
              <th>Sebep</th>
            </tr>
          </thead>
          <tbody>
            {trades.data.map((t) => (
              <tr key={t.id}>
                <td>{time(t.timestamp)}</td>
                <td>{t.position_id ?? "—"}</td>
                <td>{t.symbol}</td>
                <td>{t.action === "open" ? "Açılış" : t.action === "close" ? "Kapanış" : t.action}</td>
                <td>{t.side}</td>
                <td className="r">{t.quantity}</td>
                <td className="r">{price(t.price)}</td>
                <td className="r">{price(t.fee)}</td>
                <td className={`r ${pnlClass(t.pnl)}`}>{signed(t.pnl)}</td>
                <td>{t.reason ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
