import { useState } from "react";
import type { ConnectionConfig } from "../../shared/types";
import { api } from "../api";

interface Props {
  config: ConnectionConfig;
  onSaved: (c: ConnectionConfig) => void;
}

export default function Connection({ config, onSaved }: Props) {
  const [baseUrl, setBaseUrl] = useState(config.baseUrl);
  const [token, setToken] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const saved = await window.desktop.saveConfig({ baseUrl, token: token ? token : undefined });
      setBaseUrl(saved.baseUrl);
      setToken("");
      onSaved(saved);
      const s = await api.status();
      setMessage({ ok: true, text: `Bağlandı: ${s.exchange}, ${s.mode === "live" ? "CANLI" : "paper"} mod.` });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function clearToken() {
    const saved = await window.desktop.saveConfig({ baseUrl, token: "" });
    onSaved(saved);
    setMessage({ ok: true, text: "Token silindi." });
  }

  return (
    <div className="card narrow">
      <h3>Bot API bağlantısı</h3>
      <form className="form" onSubmit={(e) => void save(e)}>
        <label>
          Adres
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://127.0.0.1:8000" />
        </label>
        <label>
          API token {config.hasToken && <span className="small">(kayıtlı; değiştirmek için yenisini yazın)</span>}
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder={config.hasToken ? "••••••••" : "API_TOKEN"}
            autoComplete="off"
          />
        </label>
        <div className="row">
          <button type="submit" className="primary" disabled={busy}>
            Kaydet ve test et
          </button>
          {config.hasToken && (
            <button type="button" onClick={() => void clearToken()}>
              Token'ı sil
            </button>
          )}
        </div>
      </form>
      {message && <p className={message.ok ? "pos" : "neg"}>{message.text}</p>}
      <p className="note">
        Token bu bilgisayarda işletim sisteminin anahtar deposuyla şifrelenerek saklanır ve arayüze hiç gönderilmez.
        API varsayılan olarak yalnızca 127.0.0.1 üzerinde dinler; başka bir makineden bağlanacaksanız sunucuyu güvenli
        bir ağ (ör. VPN veya SSH tüneli) üzerinden açın.
      </p>
    </div>
  );
}
