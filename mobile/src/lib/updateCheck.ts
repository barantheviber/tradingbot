// "Yeni sürüm var" notice. At most once a day the app asks GitHub which release is the latest and,
// when it is newer than the installed one, shows a notice with a button that opens the release
// page. It never downloads or installs anything: the user installs the new version themselves.
//
// This file exists twice, byte for byte: desktop/shared/updateCheck.ts and
// mobile/src/lib/updateCheck.ts. desktop/tests/updateCheck.test.mjs fails when they differ.

export const LATEST_RELEASE_API = "https://api.github.com/repos/barantheviber/tradingbot/releases/latest";
export const CHECK_EVERY_MS = 24 * 60 * 60 * 1000;
export const REQUEST_TIMEOUT_MS = 10_000;

export const UPDATE_TITLE = "Yeni sürüm var";

export interface UpdateInfo {
  /** e.g. "0.3.2" */
  version: string;
  /** The release page, built here from the version and never taken from the response. */
  url: string;
}

/** What the app keeps between checks. */
export interface UpdateCheckState {
  lastChecked: number | null;
  latest: string | null;
  /** The version the user closed the notice for; a later one shows again. */
  dismissed: string | null;
}

const PLAIN_VERSION = /^\d{1,4}\.\d{1,4}\.\d{1,4}$/;

/** "v0.3.2" -> "0.3.2"; null for anything that is not a plain release version. */
export function releaseVersion(tag: unknown): string | null {
  if (typeof tag !== "string") return null;
  const v = tag.startsWith("v") ? tag.slice(1) : tag;
  return PLAIN_VERSION.test(v) ? v : null;
}

/** True when `latest` is a higher plain version than `current`. A development build never is. */
export function isNewer(latest: string, current: string): boolean {
  if (!PLAIN_VERSION.test(latest) || !PLAIN_VERSION.test(current)) return false;
  const a = latest.split(".").map(Number);
  const b = current.split(".").map(Number);
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
  return false;
}

export function releasePageUrl(version: string): string {
  return `https://github.com/barantheviber/tradingbot/releases/tag/v${version}`;
}

/** Whether a day has passed since the last check, successful or not (or the clock went back). */
export function dueForCheck(lastChecked: number | null, now: number): boolean {
  if (lastChecked === null || !Number.isFinite(lastChecked)) return true;
  return now - lastChecked >= CHECK_EVERY_MS || now < lastChecked;
}

/** The latest published release's version from GitHub's answer, or null. */
export function latestFromResponse(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const r = body as { tag_name?: unknown; draft?: unknown; prerelease?: unknown };
  if (r.draft === true || r.prerelease === true) return null;
  return releaseVersion(r.tag_name);
}

/** Stored state as read back from disk: anything unexpected counts as never checked. */
export function cleanState(raw: unknown): UpdateCheckState {
  const r = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const last = r.lastChecked;
  return {
    lastChecked: typeof last === "number" && Number.isFinite(last) ? last : null,
    latest: releaseVersion(r.latest),
    dismissed: releaseVersion(r.dismissed),
  };
}

/** What to show: a newer version the user has not closed the notice for, or null. */
export function updateToShow(state: UpdateCheckState, current: string): UpdateInfo | null {
  const { latest, dismissed } = state;
  if (!latest || latest === dismissed || !isNewer(latest, current)) return null;
  return { version: latest, url: releasePageUrl(latest) };
}

export interface UpdateCheckDeps {
  /** The installed version, e.g. "0.3.1". */
  current: string;
  now(): number;
  load(): Promise<unknown>;
  save(state: UpdateCheckState): Promise<void>;
  /** GETs LATEST_RELEASE_API and returns the parsed JSON; throws when offline or not 200. */
  fetchLatest(): Promise<unknown>;
}

export interface UpdateChecker {
  /**
   * Asks GitHub at most once a day (a failed attempt counts too) and says whether to show the
   * notice. Never throws: when offline or GitHub is unreachable it stays silent until tomorrow.
   */
  check(): Promise<UpdateInfo | null>;
  /** "Kapat": no notice for this version again (a later one shows again). */
  dismiss(version: unknown): Promise<void>;
}

/** "Kapat" for this version: returns the state to keep. */
export function dismissedState(state: UpdateCheckState, version: unknown): UpdateCheckState {
  const v = releaseVersion(version);
  return v ? { ...state, dismissed: v } : state;
}

/**
 * One per app. The app is the only writer of the saved state, so after the first read the state
 * in memory is the truth and every change is also written to storage. A storage that cannot be
 * written therefore never turns into a request per ask, and a check running while the user
 * presses "Kapat" cannot bring the closed notice back.
 */
export function createUpdateChecker(deps: UpdateCheckDeps): UpdateChecker {
  let memory: UpdateCheckState | null = null;
  let checking: Promise<UpdateInfo | null> | null = null;
  let saving: Promise<void> = Promise.resolve();

  async function state(): Promise<UpdateCheckState> {
    if (!memory) {
      try {
        memory = cleanState(await deps.load());
      } catch {
        memory = cleanState(null);
      }
    }
    return memory;
  }

  // Writes one at a time, always the newest state; a failed write stays in memory until the app closes.
  function keep(next: UpdateCheckState): Promise<void> {
    memory = next;
    saving = saving.then(() => deps.save(memory ?? next)).catch(() => undefined);
    return saving;
  }

  async function run(): Promise<UpdateInfo | null> {
    const now = deps.now();
    const before = await state();
    if (dueForCheck(before.lastChecked, now)) {
      let latest = before.latest;
      try {
        latest = latestFromResponse(await deps.fetchLatest()) ?? latest;
      } catch {
        // offline or GitHub unreachable: try again tomorrow
      }
      // Re-read memory: "Kapat" may have been pressed while the request was running.
      await keep({ ...(await state()), lastChecked: now, latest });
    }
    return updateToShow(await state(), deps.current);
  }

  return {
    check() {
      checking ??= run().finally(() => {
        checking = null;
      });
      return checking;
    },
    async dismiss(version) {
      await keep(dismissedState(await state(), version));
    },
  };
}
