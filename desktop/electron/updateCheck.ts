// The desktop side of the "Yeni sürüm var" notice (rules in shared/updateCheck.ts). The check runs
// in the main process and only in the installed app. It never downloads anything.

import { app, net, shell } from "electron";
import fs from "node:fs";
import path from "node:path";
import {
  checkForUpdate,
  cleanState,
  dismissedState,
  LATEST_RELEASE_API,
  releasePageUrl,
  releaseVersion,
  REQUEST_TIMEOUT_MS,
  type UpdateCheckState,
  type UpdateInfo,
} from "../shared/updateCheck";

function storeFile(): string {
  return path.join(app.getPath("userData"), "update-check.json");
}

async function load(): Promise<unknown> {
  return JSON.parse(await fs.promises.readFile(storeFile(), "utf8"));
}

async function save(state: UpdateCheckState): Promise<void> {
  await fs.promises.writeFile(storeFile(), JSON.stringify(state), "utf8");
}

async function fetchLatest(): Promise<unknown> {
  const res = await net.fetch(LATEST_RELEASE_API, {
    headers: { Accept: "application/vnd.github+json", "User-Agent": "TradingBot-desktop" },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`GitHub ${res.status}`);
  return res.json();
}

// The window asks every hour; one check at a time, so two asks never send two requests.
let checking: Promise<UpdateInfo | null> | null = null;

/** The newer release to tell the user about, or null (always null in development). */
export function availableUpdate(): Promise<UpdateInfo | null> {
  if (!app.isPackaged) return Promise.resolve(null);
  checking ??= checkForUpdate({ current: app.getVersion(), now: Date.now, load, save, fetchLatest }).finally(() => {
    checking = null;
  });
  return checking;
}

/** "Kapat": no notice for this version again (a later one shows again). */
export async function dismissUpdate(version: unknown): Promise<void> {
  await checking; // a check still writing would otherwise put the closed notice back
  let state: UpdateCheckState;
  try {
    state = cleanState(await load());
  } catch {
    state = cleanState(null);
  }
  try {
    await save(dismissedState(state, version));
  } catch {
    // the notice comes back next time; nothing else to do
  }
}

/** Opens the release page in the browser. The URL is built here, never passed in. */
export async function openReleasePage(version: unknown): Promise<void> {
  const v = releaseVersion(version);
  if (v) await shell.openExternal(releasePageUrl(v));
}
