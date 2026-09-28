import { useEffect, useRef, useState } from "react";
import { UPDATE_TITLE, type UpdateInfo } from "../../shared/updateCheck";

// The main process asks GitHub at most once a day; asking it every hour keeps an app that stays
// open for weeks up to date without extra requests.
const ASK_EVERY_MS = 60 * 60 * 1000;

/** "Yeni sürüm var": a newer release exists. It only opens the download page; it installs nothing. */
export default function UpdateBanner() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  // An answer that was on its way while "Kapat" was pressed must not bring the notice back.
  const closed = useRef<string | null>(null);

  useEffect(() => {
    let alive = true;
    const ask = () =>
      void window.desktop.updates
        .check()
        .then((u) => alive && setUpdate(u && u.version !== closed.current ? u : null))
        .catch(() => undefined);
    ask();
    const t = setInterval(ask, ASK_EVERY_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (!update) return null;

  function close() {
    if (!update) return;
    closed.current = update.version;
    void window.desktop.updates.dismiss(update.version).catch(() => undefined);
    setUpdate(null);
  }

  return (
    <div className="update-banner">
      <div>
        <b>
          {UPDATE_TITLE}: v{update.version}
        </b>
        <div className="note">
          İndirme sayfasından yeni kurulum dosyasını indirip çalıştırın. Eskisinin üstüne kurulur; ayarlarınız ve paper
          geçmişiniz korunur.
        </div>
      </div>
      <span className="spacer" />
      <button className="primary" onClick={() => void window.desktop.updates.openPage(update.version)}>
        İndirme sayfasını aç
      </button>
      <button onClick={close}>Kapat</button>
    </div>
  );
}
