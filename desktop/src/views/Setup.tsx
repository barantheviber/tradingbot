import { useState } from "react";
import type { LocalSetup, MarketType } from "../../shared/types";
import { DEFAULT_SETUP, EXCHANGES, parseSymbols, TIMEFRAMES, timeframeLabel, validateSetup } from "../../shared/types";

interface Props {
  initial: LocalSetup | null;
  firstRun: boolean;
  botRunning: boolean;
  onSaved: () => void;
}

export default function Setup({ initial, firstRun, botRunning, onSaved }: Props) {
  const start = initial ?? DEFAULT_SETUP;
  const [exchangeId, setExchangeId] = useState(start.exchangeId);
  const [marketType, setMarketType] = useState<MarketType>(start.marketType);
  const [symbols, setSymbols] = useState(start.symbols.join(", "));
  const [timeframe, setTimeframe] = useState(start.timeframe);
  const [balance, setBalance] = useState(String(start.startingBalance));
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const setup: LocalSetup = {
      exchangeId,
      marketType,
      symbols: parseSymbols(symbols),
      timeframe,
      startingBalance: Number(balance.replace(",", ".")),
    };
    const found = validateSetup(setup);
    setProblems(found);
    setSaved(false);
    if (found.length) return;
    setBusy(true);
    try {
      await window.desktop.localBot.saveSetup(setup);
      setSaved(true);
      onSaved();
    } catch (err) {
      setProblems([(err as Error).message.replace(/^Error invoking remote method '[^']+': (Error: )?/, "")]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card narrow">
      <h3>{firstRun ? "Hoş geldiniz: botu kuralım" : "Bot kurulumu"}</h3>
      <p className="note">
        Bot bu bilgisayarda, uygulamanın içinde çalışır. Her zaman <b>paper trading</b> (sanal bakiye) modundadır;
        gerçek emir göndermez ve borsa API anahtarı istemez.
      </p>
      <form className="form" onSubmit={(e) => void save(e)}>
        <label>
          Borsa
          <select value={exchangeId} onChange={(e) => setExchangeId(e.target.value)}>
            {EXCHANGES.map((x) => (
              <option key={x.id} value={x.id}>
                {x.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Piyasa
          <select value={marketType} onChange={(e) => setMarketType(e.target.value as MarketType)}>
            <option value="spot">Spot</option>
            <option value="future">Vadeli (future)</option>
            <option value="swap">Sürekli vadeli (swap)</option>
          </select>
        </label>
        <label>
          Semboller <span className="small">(virgülle ayırın)</span>
          <input value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="BTC/USDT, ETH/USDT" />
        </label>
        <label>
          Zaman dilimi
          <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
            {TIMEFRAMES.map((t) => (
              <option key={t} value={t}>
                {timeframeLabel(t)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sanal başlangıç bakiyesi (USDT)
          <input className="num-input" value={balance} onChange={(e) => setBalance(e.target.value)} inputMode="decimal" />
        </label>
        <div className="row">
          <button type="submit" className="primary" disabled={busy}>
            {firstRun ? "Kaydet ve botu başlat" : botRunning ? "Kaydet ve botu yeniden başlat" : "Kaydet"}
          </button>
        </div>
      </form>
      {problems.map((p) => (
        <p key={p} className="neg">
          {p}
        </p>
      ))}
      {saved && <p className="pos">Kaydedildi.</p>}
      {!firstRun && (
        <p className="note">
          Sanal bakiye, başlangıç bakiyesi ile kapanan işlemlerin kâr/zararının toplamıdır; başlangıç bakiyesini
          değiştirirseniz bakiye de o kadar değişir. Strateji ve risk ayarları "Strateji ayarları" sekmesinde.
        </p>
      )}
    </div>
  );
}
