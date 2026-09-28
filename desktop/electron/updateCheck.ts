// The desktop side of the "Yeni sürüm var" notice (rules in shared/updateCheck.ts). The check runs
// in the main process and only in the installed app. It never downloads anything.

import { app, net, shell } from "electron";
import fs from "node:fs";
import path from "node:path";
import {
  createUpdateChecker,
  LATEST_RELEASE_API,
  releasePageUrl,
  releaseVersion,
  REQUEST_TIMEOUT_MS,
  type UpdateChecker,
  type UpdateInfo,
} from "../shared/updateCheck";

function storeFile(): string {
  return path.join(app.getPath("userData"), "update-check.json");
}

async function fetchLatest(): Promise<unknown> {
  const res = await net.fetch(LATEST_RELEASE_API, {
    headers: { Accept: "application/vnd.github+json", "User-Agent": "TradingBot-desktop" },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`GitHub ${res.status}`);
  return res.json();
}

let checker: UpdateChecker | null = null;

function getChecker(): UpdateChecker {
  checker ??= createUpdateChecker({
    current: app.getVersion(),
    now: () => Date.now(),
    load: async () => JSON.parse(await fs.promises.readFile(storeFile(), "utf8")),
    save: (state) => fs.promises.writeFile(storeFile(), JSON.stringify(state), "utf8"),
    fetchLatest,
  });
  return checker;
}

/** The newer release to tell the user about, or null (always null in development). */
export function availableUpdate(): Promise<UpdateInfo | null> {
  return app.isPackaged ? getChecker().check() : Promise.resolve(null);
}

/** "Kapat": no notice for this version again (a later one shows again). */
export async function dismissUpdate(version: unknown): Promise<void> {
  if (app.isPackaged) await getChecker().dismiss(version);
}

/** Opens the release page in the browser. The URL is built here, never passed in. */
export async function openReleasePage(version: unknown): Promise<void> {
  const v = releaseVersion(version);
  if (v) await shell.openExternal(releasePageUrl(v));
}
