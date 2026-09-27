import { useEffect, useState } from "react";
import type { Position, Status } from "../../shared/types";
import { api } from "../api";
import CandleChart from "../components/CandleChart";
import PnlSummaryCard from "../components/PnlSummaryCard";
import PositionsTable from "../components/PositionsTable";
import WelcomeCard from "../components/WelcomeCard";
import { usePolling } from "../usePolling";

interface Props {
  status: Status | null;
  positions: Position[];
  onChanged: () => void;
  /** first-run notes (only when the bot runs inside this app) */
  showWelcome?: boolean;
}

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];
const CANDLE_REFRESH_MS = 15_000;

export default function Overview({ status, positions, onChanged, showWelcome = false }: Props) {
  const symbols = status?.symbols ?? [];
  const [symbol, setSymbol] = useState<string>("");
  const [timeframe, setTimeframe] = useState<string>("");

  useEffect(() => {
    if (!symbol && symbols.length) setSymbol(symbols[0]);
    if (!timeframe && status?.timeframe) setTimeframe(status.timeframe);
  }, [symbols, symbol, timeframe, status?.timeframe]);

  const candles = usePolling(
    () => (symbol && timeframe ? api.candles(symbol, timeframe, 300) : Promise.resolve([])),
    CANDLE_REFRESH_MS,
    [symbol, timeframe],
  );
  const pnl = usePolling(() => api.pnl(), 30_000);
  const openCount = positions.length;
  useEffect(() => {
    void pnl.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openCount]);

  const tfs = timeframe && !TIMEFRAMES.includes(timeframe) ? [timeframe, ...TIMEFRAMES] : TIMEFRAMES;

  return (
    <div className="overview">
      {showWelcome && <WelcomeCard timeframe={status?.timeframe ?? null} />}
      <div className="card chart-card">
        <div className="card-head">
          <h3>Grafik</h3>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {symbols.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
            {tfs.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          {candles.error && <span className="error-inline">{candles.error}</span>}
        </div>
        <CandleChart candles={candles.data ?? []} positions={positions.filter((p) => p.symbol === symbol)} />
      </div>
      <PnlSummaryCard summary={pnl.data} error={pnl.error} />
      <PositionsTable
        positions={positions}
        onChanged={() => {
          onChanged();
          void pnl.refresh();
        }}
      />
    </div>
  );
}
