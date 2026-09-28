// Pure helpers behind the bot the app runs on this computer (npm run build first; `npm test` does it).
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const { afterStart, afterStop, buildEnvFile, childEnv, exitReason, restartDelayMs, shouldResume, watchExit } = require(
  "../dist-electron/electron/localBotEnv.js",
);
const { DEFAULT_SETUP, durationText, nextCandleClose, parseSymbols, setupChangeWarnings, validateSetup } = require(
  "../dist-electron/shared/localBot.js",
);

test("the .env is paper only and never carries keys, the token or a live switch", () => {
  const env = buildEnvFile({ ...DEFAULT_SETUP, symbols: ["BTC/USDT", "SOL/USDT"] });
  assert.match(env, /^PAPER_TRADING=true$/m);
  assert.match(env, /^SYMBOLS=BTC\/USDT,SOL\/USDT$/m);
  for (const name of ["API_KEY", "API_SECRET", "API_TOKEN", "LIVE_TRADING_CONFIRM", "API_HOST"])
    assert.doesNotMatch(env, new RegExp(`^${name}=`, "m"));
});

test("invalid setups are rejected before anything is written", () => {
  assert.throws(() => buildEnvFile({ ...DEFAULT_SETUP, symbols: ["BTC/USDT\nPAPER_TRADING=false"] }));
  assert.throws(() => buildEnvFile({ ...DEFAULT_SETUP, exchangeId: "evil\nX=1" }));
  assert.ok(validateSetup({ ...DEFAULT_SETUP, startingBalance: 0 }).length > 0);
  assert.ok(validateSetup({ ...DEFAULT_SETUP, symbols: [] }).length > 0);
  assert.deepEqual(validateSetup(DEFAULT_SETUP), []);
});

test("symbols are normalised", () => {
  assert.deepEqual(parseSymbols(" btc/usdt, eth/usdt  btc/usdt,"), ["BTC/USDT", "ETH/USDT"]);
});

test("the child environment forces paper mode and loopback, dropping inherited trading variables", () => {
  const env = childEnv(
    { PATH: "/bin", PAPER_TRADING: "false", LIVE_TRADING_CONFIRM: "I_UNDERSTAND_THE_RISKS", API_KEY: "k", API_HOST: "0.0.0.0" },
    "tok",
    1234,
  );
  assert.equal(env.PATH, "/bin");
  assert.equal(env.PAPER_TRADING, "true");
  assert.equal(env.API_HOST, "127.0.0.1");
  assert.equal(env.API_PORT, "1234");
  assert.equal(env.API_TOKEN, "tok");
  assert.equal(env.LIVE_TRADING_CONFIRM, undefined);
  assert.equal(env.API_KEY, undefined);
});

test("exit reasons and restart backoff", () => {
  assert.equal(exitReason("log line\nSTARTUP_ERROR: SYMBOLS boş olamaz.\n"), "SYMBOLS boş olamaz.");
  assert.equal(exitReason("nothing useful"), null);
  assert.deepEqual([1, 2, 3, 4, 5, 9].map(restartDelayMs), [5000, 10000, 20000, 40000, 60000, 60000]);
});

test("the next candle close follows the UTC grid the exchanges use", () => {
  const t = Date.UTC(2026, 8, 27, 21, 50, 10);
  assert.equal(nextCandleClose("4h", t), Date.UTC(2026, 8, 28, 0, 0));
  assert.equal(nextCandleClose("1h", t), Date.UTC(2026, 8, 27, 22, 0));
  assert.equal(nextCandleClose("15m", t), Date.UTC(2026, 8, 27, 22, 0));
  assert.equal(nextCandleClose("1d", t), Date.UTC(2026, 8, 28));
  assert.equal(nextCandleClose("4h", Date.UTC(2026, 8, 27, 20)), Date.UTC(2026, 8, 28));
  assert.equal(nextCandleClose("1w", t), null);
  assert.equal(nextCandleClose("7h", t), null);
  assert.equal(durationText(135 * 60_000), "2 sa 15 dk");
  assert.equal(durationText(10_000), "1 dk");
  assert.equal(durationText(4 * 3_600_000), "4 sa");
});

test("after a restart the bot comes back only if it was running, never after Durdur", () => {
  const set = { setup: DEFAULT_SETUP };
  assert.equal(shouldResume(set), false, "set up but never started");
  const running = afterStart(set);
  assert.equal(shouldResume(running), true, "running when the PC went down (no clean quit)");
  assert.equal(shouldResume(afterStop(running, false)), true, "running when the app quit");
  const stopped = afterStop(running, true);
  assert.equal(shouldResume(stopped), false, "stopped with Durdur, e.g. before moving to the phone");
  assert.equal(shouldResume(afterStop(stopped, false)), false, "and quitting afterwards keeps it stopped");
  assert.equal(shouldResume({ autoStart: true }), false, "no setup");
});

test("a bot program that cannot start counts as gone, so Durdur never waits for it", async () => {
  const calls = [];
  const missing = spawn("/nonexistent/tradingbot-core", ["run"], { stdio: ["pipe", "pipe", "pipe"] });
  await watchExit(missing, (code, err) => calls.push([code, err?.code]));
  assert.deepEqual(calls, [[null, "ENOENT"]]);

  const exits = [];
  const quick = spawn(process.execPath, ["-e", "process.exit(3)"], { stdio: ["pipe", "pipe", "pipe"] });
  await watchExit(quick, (code, err) => exits.push([code, err]));
  assert.deepEqual(exits, [[3, null]]);
});

test("saving a setup warns about open positions", () => {
  const before = { ...DEFAULT_SETUP, symbols: ["BTC/USDT", "ETH/USDT"] };
  assert.deepEqual(setupChangeWarnings(null, before, ["BTC/USDT"]), [], "first setup");
  assert.deepEqual(setupChangeWarnings(before, { ...before, timeframe: "1h" }, ["BTC/USDT"]), []);
  assert.deepEqual(setupChangeWarnings(before, { ...before, symbols: ["BTC/USDT"] }, []), [], "nothing open");

  const dropped = setupChangeWarnings(before, { ...before, symbols: ["BTC/USDT"] }, ["ETH/USDT", "ETH/USDT"]);
  assert.equal(dropped.length, 1);
  assert.match(dropped[0], /^ETH\/USDT listeden çıkıyor/);

  const moved = setupChangeWarnings(before, { ...before, exchangeId: "bybit" }, ["BTC/USDT"]);
  assert.equal(moved.length, 1);
  assert.match(moved[0], /stop-loss çalışmayabilir/);

  // since #24 a changed virtual balance counts as a deposit or withdrawal, not as profit or loss
  assert.deepEqual(setupChangeWarnings(before, { ...before, startingBalance: 5000 }, []), []);
});

test("the app refuses a second copy of itself (two bots on one data folder)", () => {
  const main = fs.readFileSync(new URL("../electron/main.ts", import.meta.url), "utf8");
  assert.match(main, /requestSingleInstanceLock\(\)/);
  assert.match(main, /whenReady\(\)\.then\(\(\) => \{\n\s+if \(!primary\) return;/);
});
