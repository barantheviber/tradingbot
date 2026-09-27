// Pure helpers behind the bot the app runs on this computer (npm run build first; `npm test` does it).
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const { buildEnvFile, childEnv, exitReason, restartDelayMs } = require("../dist-electron/electron/localBotEnv.js");
const { DEFAULT_SETUP, parseSymbols, validateSetup } = require("../dist-electron/shared/localBot.js");

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
