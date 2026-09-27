import { useState } from "react";
import type { Setting, SettingValue } from "../../shared/types";
import { api } from "../api";
import { time } from "../format";
import { usePolling } from "../usePolling";

export default function Settings() {
  const settings = usePolling(() => api.settings(), 0);
  const [filter, setFilter] = useState("");

  const rows = (settings.data ?? []).filter(
    (s) => !filter || s.key.includes(filter.toLowerCase()) || s.description.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="card">
      <div className="card-head">
        <h3>Strateji ve risk ayarları</h3>
        <input placeholder="Ara…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <button onClick={() => void settings.refresh()}>Yenile</button>
        {settings.error && <span className="error-inline">{settings.error}</span>}
      </div>
      <p className="note">
        Değişiklikler botun ayar tablosuna yazılır ve bot bir sonraki kapanan mumda kullanır. Paper/canlı mod buradan
        değiştirilemez.
      </p>
      {!rows.length ? (
        <p className="empty">{settings.loading ? "Yükleniyor…" : "Ayar yok."}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Anahtar</th>
              <th>Değer</th>
              <th>Açıklama</th>
              <th>Güncellendi</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <SettingRow
                key={s.key}
                setting={s}
                onSaved={(updated) =>
                  settings.setData((prev) => (prev ?? []).map((x) => (x.key === updated.key ? updated : x)))
                }
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function SettingRow({ setting, onSaved }: { setting: Setting; onSaved: (s: Setting) => void }) {
  const [draft, setDraft] = useState<string>(String(setting.value));
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const isBool = typeof setting.value === "boolean";
  const isNum = typeof setting.value === "number";

  async function save(value: SettingValue) {
    setState("saving");
    setError(null);
    try {
      const updated = await api.updateSetting(setting.key, value);
      onSaved(updated);
      setDraft(String(updated.value));
      setState("saved");
    } catch (e) {
      setError((e as Error).message);
      setState("error");
    }
  }

  function submit() {
    if (isNum) {
      const n = Number(draft.replace(",", "."));
      if (!Number.isFinite(n)) {
        setError("Sayı girin");
        setState("error");
        return;
      }
      void save(n);
    } else {
      void save(draft);
    }
  }

  const dirty = draft !== String(setting.value);

  return (
    <tr>
      <td className="mono">{setting.key}</td>
      <td className="setting-value">
        {isBool ? (
          <label className="switch">
            <input
              type="checkbox"
              checked={setting.value as boolean}
              disabled={state === "saving"}
              onChange={(e) => void save(e.target.checked)}
            />
            <span>{setting.value ? "Açık" : "Kapalı"}</span>
          </label>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <input
              className={isNum ? "num-input" : ""}
              inputMode={isNum ? "decimal" : undefined}
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                setState("idle");
              }}
            />
            <button type="submit" disabled={!dirty || state === "saving"}>
              Kaydet
            </button>
          </form>
        )}
        {state === "saved" && <span className="pos small">Kaydedildi</span>}
        {error && <span className="error-inline small">{error}</span>}
      </td>
      <td>{setting.description}</td>
      <td className="small">{time(setting.updated_at)}</td>
    </tr>
  );
}
