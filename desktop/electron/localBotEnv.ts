// Pure helpers for the bundled bot process: what goes into its .env and its environment.
// Kept free of Electron imports so the tests can load them directly.

import type { ChildProcess } from "node:child_process";
import type { LocalSetup } from "../shared/localBot";
import { validateSetup } from "../shared/localBot";

export const LOCAL_API_PORT = 47821;

/** Every variable config.py reads. The child never inherits them from the user's environment. */
const CONFIG_ENV_NAMES = [
  "SYMBOLS", "EXCHANGE_ID", "MARKET_TYPE", "USE_TESTNET", "API_KEY", "API_SECRET", "API_PASSWORD",
  "PAPER_TRADING", "LIVE_TRADING_CONFIRM", "TIMEFRAME", "OHLCV_LIMIT", "POLL_INTERVAL_SEC", "DB_PATH",
  "LOG_DIR", "LOG_LEVEL", "PAPER_STARTING_BALANCE", "PAPER_FEE_RATE", "PAPER_SLIPPAGE_BPS", "MAX_RETRIES",
  "RETRY_BASE_DELAY", "RETRY_MAX_DELAY", "API_HOST", "API_PORT", "API_TOKEN", "API_CORS_ORIGINS",
];

/**
 * The .env the app writes into the bot's data folder. It never holds exchange keys, the API
 * token or a live-trading switch: the app only ever runs the bot in paper mode.
 */
export function buildEnvFile(setup: LocalSetup): string {
  const problems = validateSetup(setup);
  if (problems.length) throw new Error(problems.join(" "));
  return [
    "# Written by the Trading Bot app. Edit the setup in the app instead of this file.",
    `EXCHANGE_ID=${setup.exchangeId}`,
    `MARKET_TYPE=${setup.marketType}`,
    `SYMBOLS=${setup.symbols.join(",")}`,
    `TIMEFRAME=${setup.timeframe}`,
    `PAPER_STARTING_BALANCE=${setup.startingBalance}`,
    "PAPER_TRADING=true",
    "DB_PATH=data/tradingbot.db",
    "LOG_DIR=logs",
    "",
  ].join("\n");
}

/**
 * Environment for the bot process. Variables set here win over the .env file (python-dotenv
 * does not override), so paper mode, the loopback port and the token are fixed by the app.
 */
export function childEnv(base: NodeJS.ProcessEnv, token: string, port = LOCAL_API_PORT): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...base };
  for (const name of CONFIG_ENV_NAMES) delete env[name];
  return {
    ...env,
    PAPER_TRADING: "true",
    API_HOST: "127.0.0.1",
    API_PORT: String(port),
    API_TOKEN: token,
    PYTHONUNBUFFERED: "1",
    PYTHONIOENCODING: "utf-8",
  };
}

/** Pulls the readable reason out of the core's stderr (STARTUP_ERROR / RUNTIME_ERROR lines). */
export function exitReason(stderrTail: string): string | null {
  const lines = stderrTail.split(/\r?\n/).reverse();
  for (const line of lines) {
    const m = /^(?:STARTUP_ERROR|RUNTIME_ERROR): (.+)$/.exec(line.trim());
    if (m) return m[1];
  }
  return null;
}

/**
 * Calls onGone exactly once when the bot process is gone, and resolves then. A process that never
 * started (the exe missing, or blocked by an antivirus) sends "error" and no "exit"; without this
 * the app showed it as running and Durdur waited for it forever.
 */
export function watchExit(
  child: ChildProcess,
  onGone: (code: number | null, startError: Error | null) => void,
): Promise<void> {
  return new Promise((resolve) => {
    let gone = false;
    const finish = (code: number | null, startError: Error | null) => {
      if (gone) return;
      gone = true;
      onGone(code, startError);
      resolve();
    };
    child.once("exit", (code) => finish(code, null));
    child.on("error", (err) => {
      if (child.pid === undefined) finish(null, err);
    });
  });
}

/** Restart delay after the n-th consecutive crash: 5 s, 10 s, 20 s ... capped at 60 s. */
export function restartDelayMs(attempt: number): number {
  return Math.min(60_000, 5_000 * 2 ** Math.max(0, attempt - 1));
}

/**
 * What the app remembers between launches (userData/local-bot.json). The bot starts by itself on
 * launch only if it was running when the app or the computer last went down: a bot the user
 * stopped with Durdur stays stopped. The user moves between the PC and the phone by pressing
 * Durdur on one first, and two bots must never trade the same account.
 */
export interface Stored {
  setup?: LocalSetup;
  /** the bot was running when the app last closed: start it again on launch */
  autoStart?: boolean;
}

export function afterStart(s: Stored): Stored {
  return { ...s, autoStart: true };
}

/** byUser=false (a restart, or the app shutting down) keeps autoStart as it is. */
export function afterStop(s: Stored, byUser: boolean): Stored {
  return byUser ? { ...s, autoStart: false } : s;
}

export function shouldResume(s: Stored): boolean {
  return Boolean(s.setup && s.autoStart);
}
