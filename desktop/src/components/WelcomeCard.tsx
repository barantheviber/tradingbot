import { useState } from "react";
import { candleNote } from "../../shared/types";

const KEY = "tradingbot.welcomeDismissed";

function dismissed(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

/** First-run notes shown above the overview until the user closes them. */
export default function WelcomeCard({ timeframe }: { timeframe: string | null }) {
  const [hidden, setHidden] = useState(dismissed);
  if (hidden) return null;

  function close() {
    try {
      localStorage.setItem(KEY, "1");
    } catch {
      // storage unavailable: it just shows again next time
    }
    setHidden(true);
  }

  return (
    <div className="card welcome">
      <div className="card-head">
        <h3>Bot hazır. Bilmeniz gereken birkaç şey</h3>
        <span className="spacer" />
        <button onClick={close}>Anladım</button>
      </div>
      <ul>
        <li>{candleNote(timeframe)}</li>
        <li>
          Her şey <b>paper trading</b> (sanal bakiye) ile olur, gerçek emir gönderilmez.
        </li>
        <li>
          Bot bu uygulama açıkken çalışır. Uygulamayı kapatırsanız bot durur; tekrar açtığınızda kaldığı yerden devam eder.
        </li>
        <li>
          <b>Telefona geçerken:</b> üstteki "Durdur"a basıp "Pozisyonları kapat ve durdur"u seçin, sonra telefonda botu
          başlatın. İki cihaz birbirinin pozisyonlarını bilmez.
        </li>
        <li>Ayarları "Strateji ayarları" sekmesinden, borsa ve sembolleri "Kurulum" sekmesinden değiştirebilirsiniz.</li>
      </ul>
    </div>
  );
}
