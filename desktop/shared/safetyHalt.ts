// Turkish text for the automatic brake (api/service.py _safety_halt). Same wording as
// mobile/src/lib/safetyHalt.ts (keep the two in sync).
import type { SafetyHalt } from "./apiTypes";

export const SAFETY_HALT_TITLE = "Otomatik fren devrede: yeni pozisyon açılmıyor";

export const SAFETY_HALT_HINT =
  "Açık pozisyonlar stop, hedef ve trailing ile yönetilmeye devam eder; hiçbir şey zorla kapatılmaz. " +
  'Durumu kontrol ettikten sonra "Freni kaldır"a basın. Bu, zirveyi ve zarar serisini sıfırlar.';

function pct(v: number | null): string {
  return v === null ? "?" : v.toFixed(1).replace(".", ",");
}

/** Why the brake is on, in one sentence. */
export function safetyHaltReason(h: SafetyHalt): string {
  switch (h.kind) {
    case "drawdown":
      return `Özsermaye zirvesinden %${pct(h.drawdown_pct)} düştü (sınır %${pct(h.drawdown_limit_pct)}).`;
    case "losing_streak":
      return `Art arda ${h.losing_streak_at_halt ?? h.losing_streak} işlem zararla kapandı (sınır ${h.losing_streak_limit}).`;
    case "manual":
      return "Ayarlardan elle açıldı.";
    default:
      return h.reason ?? "Bot bir güvenlik sınırına ulaştı.";
  }
}
