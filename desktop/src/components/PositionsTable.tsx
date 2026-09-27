import { useState } from "react";
import type { Position } from "../../shared/types";
import { api } from "../api";
import { followCommand } from "../commands";
import { pnlClass, price, signed, time } from "../format";

interface Props {
  positions: Position[];
  onChanged: () => void;
}

export default function PositionsTable({ positions, onChanged }: Props) {
  const [busy, setBusy] = useState<number | null>(null);
  const [queued, setQueued] = useState<Set<number>>(new Set());
  const [message, setMessage] = useState<string | null>(null);

  async function close(p: Position) {
    const ok = window.confirm(
      `${p.symbol} ${p.side.toUpperCase()} pozisyonu (#${p.id}) kapatılsın mı?\n\n` +
        "Uygulama emir göndermez; bot kapatma komutunu bir sonraki döngüsünde işler.",
    );
    if (!ok) return;
    setBusy(p.id);
    setMessage(null);
    try {
      const res = await api.closePosition(p.id);
      setQueued((prev) => new Set(prev).add(p.id));
      setMessage(
        res.already_queued
          ? `#${p.id} için kapatma komutu zaten kuyrukta (komut ${res.command_id}).`
          : `#${p.id} için kapatma komutu kuyruğa alındı (komut ${res.command_id}).`,
      );
      onChanged();
      void followCommand(res.command_id).then((cmd) => {
        setQueued((prev) => {
          const next = new Set(prev);
          next.delete(p.id);
          return next;
        });
        if (!cmd) setMessage(`#${p.id}: bot komutu henüz işlemedi. Bot çalışıyor mu?`);
        else if (cmd.status === "done") setMessage(`#${p.id} kapatıldı.${cmd.note ? ` (${cmd.note})` : ""}`);
        else setMessage(`#${p.id} kapatılamadı: ${cmd.note || "bot komutu reddetti"}`);
        onChanged();
      });
    } catch (e) {
      setMessage(`Kapatma komutu gönderilemedi: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>Açık pozisyonlar ({positions.length})</h3>
        {message && <span className="note">{message}</span>}
      </div>
      {positions.length === 0 ? (
        <p className="empty">Açık pozisyon yok.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Sembol</th>
              <th>Yön</th>
              <th className="r">Miktar</th>
              <th className="r">Giriş</th>
              <th className="r">Son fiyat</th>
              <th className="r">Stop</th>
              <th className="r">Trailing</th>
              <th className="r">Kâr al</th>
              <th className="r">Gerçekleşmemiş PnL</th>
              <th>Açılış</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const pending = p.close_pending || queued.has(p.id);
              return (
                <tr key={p.id}>
                  <td>{p.id}</td>
                  <td>{p.symbol}</td>
                  <td className={p.side === "long" ? "pos" : "neg"}>{p.side === "long" ? "LONG" : "SHORT"}</td>
                  <td className="r">{p.quantity}</td>
                  <td className="r">{price(p.entry_price)}</td>
                  <td className="r">{price(p.current_price)}</td>
                  <td className="r">{price(p.stop_loss)}</td>
                  <td className="r">{price(p.trailing_stop)}</td>
                  <td className="r">{price(p.take_profit)}</td>
                  <td className={`r ${pnlClass(p.unrealized_pnl)}`}>{signed(p.unrealized_pnl)}</td>
                  <td>{time(p.opened_at)}</td>
                  <td className="r">
                    <button className="danger" disabled={busy === p.id || pending} onClick={() => void close(p)}>
                      {pending ? "Kapatılıyor…" : "Kapat"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
