import { useState } from "react";
import type { LocalBotState, Position, Status } from "../../shared/types";
import { api } from "../api";
import { followCommand } from "../commands";

interface Props {
  state: LocalBotState;
  positions: Position[];
  status: Status | null;
  onChanged: () => void;
}

const PHASE_LABEL: Record<LocalBotState["phase"], string> = {
  stopped: "Bot durdu",
  starting: "Bot başlıyor…",
  running: "Bot çalışıyor",
  stopping: "Bot duruyor…",
  restarting: "Yeniden başlatılıyor",
  error: "Bot başlatılamadı",
};

/** Start/stop for the bot on this computer. Stopping with open positions asks what to do first. */
export default function BotControl({ state, positions, status, onChanged }: Props) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const active = state.phase === "running" || state.phase === "starting" || state.phase === "restarting";

  async function start() {
    setError(null);
    setBusy("Başlatılıyor…");
    try {
      await window.desktop.localBot.start();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function stop() {
    setAsking(false);
    setBusy("Durduruluyor…");
    try {
      await window.desktop.localBot.stop();
    } finally {
      setBusy(null);
      onChanged();
    }
  }

  async function closeAllThenStop() {
    setAsking(false);
    setError(null);
    setBusy(`${positions.length} pozisyon kapatılıyor…`);
    try {
      const queued = await Promise.all(positions.map((p) => api.closePosition(p.id)));
      onChanged();
      const results = await Promise.all(queued.map((q) => followCommand(q.command_id)));
      const failed = results.filter((r) => !r || r.status !== "done").length;
      if (failed > 0) {
        setError(`${failed} pozisyon kapatılamadı; bot çalışmaya devam ediyor. Loglar sekmesine bakın.`);
        return;
      }
      setBusy("Durduruluyor…");
      await window.desktop.localBot.stop();
    } catch (e) {
      setError(`Kapatma komutu gönderilemedi: ${(e as Error).message}`);
    } finally {
      setBusy(null);
      onChanged();
    }
  }

  return (
    <div className={`botcontrol botcontrol-${state.phase}`}>
      <span className="botcontrol-label">{busy ?? PHASE_LABEL[state.phase]}</span>
      {!busy && state.phase === "running" && status && !status.bot_running && (
        <span className="note">Borsaya bağlanmaya çalışıyor; internet bağlantınızı kontrol edin.</span>
      )}
      {state.message && <span className="note">{state.message}</span>}
      {error && <span className="neg">{error}</span>}
      <span className="spacer" />
      {active ? (
        <button
          className="danger"
          disabled={Boolean(busy) || state.phase === "stopping"}
          onClick={() => (positions.length > 0 ? setAsking(true) : void stop())}
        >
          Durdur
        </button>
      ) : (
        <button className="primary" disabled={Boolean(busy) || state.phase === "stopping"} onClick={() => void start()}>
          Başlat
        </button>
      )}
      {asking && (
        <div className="modal-backdrop" onClick={() => setAsking(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{positions.length} açık pozisyon var</h3>
            <p>
              Bot durunca bu pozisyonların stop-loss, kâr al ve trailing takibi de durur. Bot bu bilgisayarda tekrar
              başlayınca kaldığı yerden devam eder, ama telefondaki bot bu pozisyonları bilmez.
            </p>
            <p className="note">Telefona geçecekseniz önce pozisyonları kapatın.</p>
            <div className="row">
              <button className="primary" onClick={() => void closeAllThenStop()}>
                Pozisyonları kapat ve durdur
              </button>
              <button className="danger" onClick={() => void stop()}>
                Pozisyonları bırak, sadece durdur
              </button>
              <button onClick={() => setAsking(false)}>Vazgeç</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
