import { app, safeStorage } from "electron";
import fs from "node:fs";
import path from "node:path";
import type { ConnectionConfig } from "../shared/types";

interface StoredConfig {
  baseUrl: string;
  /** base64 of the safeStorage-encrypted token, or of the plain token when the OS has no keychain */
  token?: string;
  tokenEncrypted?: boolean;
}

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

function file(): string {
  return path.join(app.getPath("userData"), "connection.json");
}

function read(): StoredConfig {
  try {
    const parsed = JSON.parse(fs.readFileSync(file(), "utf8")) as StoredConfig;
    return { baseUrl: parsed.baseUrl || DEFAULT_BASE_URL, token: parsed.token, tokenEncrypted: parsed.tokenEncrypted };
  } catch {
    return { baseUrl: process.env.TRADINGBOT_API_URL || DEFAULT_BASE_URL };
  }
}

function write(cfg: StoredConfig): void {
  fs.mkdirSync(path.dirname(file()), { recursive: true });
  fs.writeFileSync(file(), JSON.stringify(cfg, null, 2), { encoding: "utf8", mode: 0o600 });
}

export function getPublicConfig(): ConnectionConfig {
  const cfg = read();
  return { baseUrl: cfg.baseUrl, hasToken: Boolean(cfg.token) || Boolean(process.env.TRADINGBOT_API_TOKEN) };
}

export function getToken(): string {
  const cfg = read();
  if (cfg.token) {
    const raw = Buffer.from(cfg.token, "base64");
    return cfg.tokenEncrypted ? safeStorage.decryptString(raw) : raw.toString("utf8");
  }
  return process.env.TRADINGBOT_API_TOKEN || "";
}

export function saveConfig(baseUrl: string, token?: string): ConnectionConfig {
  const cfg = read();
  cfg.baseUrl = baseUrl;
  if (token !== undefined) {
    if (!token) {
      delete cfg.token;
      delete cfg.tokenEncrypted;
    } else if (safeStorage.isEncryptionAvailable()) {
      cfg.token = safeStorage.encryptString(token).toString("base64");
      cfg.tokenEncrypted = true;
    } else {
      cfg.token = Buffer.from(token, "utf8").toString("base64");
      cfg.tokenEncrypted = false;
    }
  }
  write(cfg);
  return getPublicConfig();
}
