// "Yeni sürüm var" notice (npm run build first; `npm test` does it). The rule: at most one
// request a day, a notice with a link to the release page, and never a download or an install.
import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  CHECK_EVERY_MS,
  LATEST_RELEASE_API,
  cleanState,
  createUpdateChecker,
  dismissedState,
  dueForCheck,
  isNewer,
  latestFromResponse,
  releasePageUrl,
  releaseVersion,
  updateToShow,
} = require("../dist-electron/shared/updateCheck.js");

const read = (p) => fs.readFileSync(new URL(p, import.meta.url), "utf8");
const DAY = CHECK_EVERY_MS;
const T0 = Date.UTC(2026, 8, 28, 12);

test("the desktop and phone copies of the rules are the same file", () => {
  assert.equal(read("../../mobile/src/lib/updateCheck.ts"), read("../shared/updateCheck.ts"));
});

test("only plain release versions count", () => {
  assert.equal(releaseVersion("v0.3.2"), "0.3.2");
  assert.equal(releaseVersion("0.3.2"), "0.3.2");
  for (const bad of ["v0.3.2-rc1", "0.0.0-dev", "latest", "v1.2", "../x", "", null, 3, undefined])
    assert.equal(releaseVersion(bad), null, String(bad));
});

test("versions compare as numbers, and a development build never sees a newer one", () => {
  assert.ok(isNewer("0.3.2", "0.3.1"));
  assert.ok(isNewer("0.3.10", "0.3.9"));
  assert.ok(isNewer("1.0.0", "0.9.9"));
  assert.ok(!isNewer("0.3.1", "0.3.1"));
  assert.ok(!isNewer("0.3.0", "0.3.1"));
  assert.ok(!isNewer("0.3.2", "0.0.0-dev"));
  assert.ok(!isNewer("0.3.2-rc1", "0.3.1"));
});

test("GitHub is asked at most once a day", () => {
  assert.ok(dueForCheck(null, T0));
  assert.ok(!dueForCheck(T0, T0 + 1));
  assert.ok(!dueForCheck(T0, T0 + DAY - 1));
  assert.ok(dueForCheck(T0, T0 + DAY));
  assert.ok(dueForCheck(T0, T0 - 60_000), "a clock set back does not stop the checks for good");
  assert.ok(dueForCheck(Number.NaN, T0));
});

test("drafts, pre-releases and odd answers are ignored", () => {
  assert.equal(latestFromResponse({ tag_name: "v0.3.2" }), "0.3.2");
  assert.equal(latestFromResponse({ tag_name: "v0.3.2", prerelease: true }), null);
  assert.equal(latestFromResponse({ tag_name: "v0.3.2", draft: true }), null);
  assert.equal(latestFromResponse({ tag_name: "v0.3.2-beta" }), null);
  assert.equal(latestFromResponse({ message: "Not Found" }), null);
  assert.equal(latestFromResponse("v0.3.2"), null);
  assert.equal(latestFromResponse(null), null);
});

test("the link always goes to this repository's release page", () => {
  assert.equal(releasePageUrl("0.3.2"), "https://github.com/barantheviber/tradingbot/releases/tag/v0.3.2");
  assert.equal(LATEST_RELEASE_API, "https://api.github.com/repos/barantheviber/tradingbot/releases/latest");
});

test("a closed notice stays closed for that version and comes back for the next one", () => {
  const s = { lastChecked: T0, latest: "0.3.2", dismissed: null };
  assert.deepEqual(updateToShow(s, "0.3.1"), {
    version: "0.3.2",
    url: "https://github.com/barantheviber/tradingbot/releases/tag/v0.3.2",
  });
  const closed = dismissedState(s, "0.3.2");
  assert.equal(updateToShow(closed, "0.3.1"), null);
  assert.equal(updateToShow({ ...closed, latest: "0.3.3" }, "0.3.1")?.version, "0.3.3");
  assert.equal(updateToShow(s, "0.3.2"), null, "no notice once the new version is installed");
  assert.deepEqual(dismissedState(s, "evil"), s);
});

test("saved state that is damaged or edited counts as never checked", () => {
  assert.deepEqual(cleanState(null), { lastChecked: null, latest: null, dismissed: null });
  assert.deepEqual(cleanState("{"), { lastChecked: null, latest: null, dismissed: null });
  assert.deepEqual(cleanState({ lastChecked: "x", latest: "javascript:alert(1)", dismissed: 5 }), {
    lastChecked: null,
    latest: null,
    dismissed: null,
  });
});

function fakeDeps({ now = T0, stored = null, answer = { tag_name: "v0.3.2" }, current = "0.3.1" } = {}) {
  const d = {
    requests: 0,
    saves: 0,
    saved: stored,
    clock: now,
    current,
    now: () => d.clock,
    load: async () => d.saved,
    save: async (s) => {
      d.saves += 1;
      d.saved = JSON.parse(JSON.stringify(s));
    },
    fetchLatest: async () => {
      d.requests += 1;
      if (answer instanceof Error) throw answer;
      return answer;
    },
  };
  return d;
}

test("a newer release shows the notice, with the link built from the version", async () => {
  const d = fakeDeps({ answer: { tag_name: "v0.3.2", html_url: "https://evil.example/download.exe" } });
  const u = await createUpdateChecker(d).check();
  assert.deepEqual(u, { version: "0.3.2", url: "https://github.com/barantheviber/tradingbot/releases/tag/v0.3.2" });
  assert.equal(d.requests, 1);
  assert.equal(d.saved.latest, "0.3.2");
  assert.equal(d.saved.lastChecked, T0);
});

test("within a day the saved answer is used without asking GitHub again", async () => {
  const d = fakeDeps();
  await createUpdateChecker(d).check();
  d.clock = T0 + DAY - 1;
  // a restarted app reads the saved state
  assert.equal((await createUpdateChecker(d).check())?.version, "0.3.2");
  assert.equal(d.requests, 1);
  d.clock = T0 + DAY;
  await createUpdateChecker(d).check();
  assert.equal(d.requests, 2);
});

test("asks that overlap send one request", async () => {
  const d = fakeDeps();
  const checker = createUpdateChecker(d);
  const [a, b] = await Promise.all([checker.check(), checker.check()]);
  assert.equal(a?.version, "0.3.2");
  assert.equal(b?.version, "0.3.2");
  assert.equal(d.requests, 1);
});

test("offline: no notice, no error, and no second try the same day", async () => {
  const d = fakeDeps({ answer: new Error("offline") });
  const checker = createUpdateChecker(d);
  assert.equal(await checker.check(), null);
  assert.equal(d.saved.lastChecked, T0);
  d.clock = T0 + 60_000;
  assert.equal(await checker.check(), null);
  assert.equal(d.requests, 1);
});

test("an earlier answer survives a failed check", async () => {
  const d = fakeDeps({ stored: { lastChecked: T0 - DAY, latest: "0.3.2", dismissed: null }, answer: new Error("503") });
  assert.equal((await createUpdateChecker(d).check())?.version, "0.3.2");
});

test("storage that fails to read or write never breaks the check or sends extra requests", async () => {
  const d = fakeDeps();
  d.load = async () => {
    throw new Error("unreadable");
  };
  d.save = async () => {
    throw new Error("disk full");
  };
  const checker = createUpdateChecker(d);
  for (let hour = 0; hour < 24; hour++) {
    d.clock = T0 + hour * 3_600_000;
    assert.equal((await checker.check())?.version, "0.3.2");
  }
  assert.equal(d.requests, 1, "still at most one request a day");
  await checker.dismiss("0.3.2");
  assert.equal(await checker.check(), null, "Kapat works even when it cannot be saved");
});

test("Kapat pressed while the daily request is running keeps the notice closed", async () => {
  const d = fakeDeps({ stored: { lastChecked: T0 - DAY, latest: "0.3.2", dismissed: null } });
  let answer;
  d.fetchLatest = () => {
    d.requests += 1;
    return new Promise((resolve) => (answer = resolve));
  };
  const checker = createUpdateChecker(d);
  const running = checker.check();
  await new Promise((r) => setImmediate(r));
  const closing = checker.dismiss("0.3.2");
  answer({ tag_name: "v0.3.2" });
  assert.equal(await running, null);
  await closing;
  assert.equal(await checker.check(), null);
  assert.equal(d.saved.dismissed, "0.3.2");
  assert.equal(d.saved.lastChecked, T0);
  assert.equal(await createUpdateChecker(d).check(), null, "and after a restart");
});

test("a closed notice comes back for the next release", async () => {
  const d = fakeDeps();
  const checker = createUpdateChecker(d);
  await checker.check();
  await checker.dismiss("0.3.2");
  d.clock = T0 + DAY;
  d.fetchLatest = async () => ({ tag_name: "v0.3.3" });
  assert.equal((await checker.check())?.version, "0.3.3");
});

test("the installed version is never nagged about itself or an older release", async () => {
  assert.equal(await createUpdateChecker(fakeDeps({ current: "0.3.2" })).check(), null);
  assert.equal(await createUpdateChecker(fakeDeps({ current: "0.4.0" })).check(), null);
  assert.equal(await createUpdateChecker(fakeDeps({ current: "0.0.0-dev" })).check(), null);
});

test("builds that are not releases carry a version that never shows the notice", () => {
  assert.equal(JSON.parse(read("../package.json")).version, "0.0.0-dev");
  assert.equal(JSON.parse(read("../../mobile/app.json")).expo.version, "0.0.0-dev");
  assert.equal(releaseVersion("0.0.0-dev"), null);
});

test("neither app downloads or installs updates by itself", () => {
  const sources = [
    "../electron/updateCheck.ts",
    "../electron/main.ts",
    "../electron/preload.ts",
    "../src/components/UpdateBanner.tsx",
    "../../mobile/src/components/UpdateCard.tsx",
  ].map(read);
  for (const src of sources) {
    assert.doesNotMatch(src, /electron-updater|autoUpdater|downloadURL|\.downloadAsync|expo-updates|expo-file-system/);
  }
  const pkg = JSON.parse(read("../package.json"));
  const mobilePkg = JSON.parse(read("../../mobile/package.json"));
  for (const deps of [pkg.dependencies, pkg.devDependencies, mobilePkg.dependencies, mobilePkg.devDependencies])
    for (const name of ["electron-updater", "expo-updates"]) assert.ok(!(name in (deps ?? {})), name);
  // The desktop opens the page from the version alone; the window cannot hand it a URL.
  const desktopCheck = read("../electron/updateCheck.ts");
  assert.match(desktopCheck, /shell\.openExternal\(releasePageUrl\(v\)\)/);
  assert.doesNotMatch(read("../electron/preload.ts"), /updates:openPage", url/);
});
