import { useState } from "react";
import { SAFETY_HALT_HINT, SAFETY_HALT_TITLE, safetyHaltReason } from "../../shared/safetyHalt";
import type { Status } from "../../shared/types";
import { api } from "../api";

/** Shown on every tab while the automatic brake keeps the bot from opening new positions. */
export default function SafetyHaltBanner({ status, onChanged }: { status: Status | null; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const halt = status?.safety_halt;
  if (!halt?.active) return null;

  async function release() {
    if (!window.confirm("Fren kaldırılsın mı? Bot yeniden yeni pozisyon açabilir; zirve ve zarar serisi sıfırlanır.")) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateSetting("safety_halt_active", false);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="halt-banner">
      <div>
        <b>{SAFETY_HALT_TITLE}</b>
        <div>{safetyHaltReason(halt)}</div>
        <div className="note">{SAFETY_HALT_HINT}</div>
        {error && <div className="neg small">{error}</div>}
      </div>
      <span className="spacer" />
      <button className="primary" disabled={busy} onClick={() => void release()}>
        Freni kaldır
      </button>
    </div>
  );
}
