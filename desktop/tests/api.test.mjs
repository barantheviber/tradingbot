// Runs the compiled main-process code (npm run build first; `npm test` does it) against the
// real API from api/, started with sample data by `python -m api.demo`. Set PYTHON to pick the
// interpreter (default: python3) that has requirements.txt installed.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import path from "node:path";
import { after, before, test } from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import WebSocket from "ws";

const require = createRequire(import.meta.url);
const { buildRequest, normaliseBaseUrl, wsUrl } = require("../dist-electron/electron/apiRoutes.js");
const { performCall } = require("../dist-electron/electron/apiClient.js");

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const TOKEN = "desktop-test-token-0123456789";
let server;
let base;

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function waitUntilUp(url, deadlineMs) {
  const until = Date.now() + deadlineMs;
  while (Date.now() < until) {
    if (server.exitCode !== null) throw new Error(`demo API exited with code ${server.exitCode}`);
    try {
      await fetch(url);
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  throw new Error("demo API did not start in time");
}

before(async () => {
  const port = await freePort();
  base = `http://127.0.0.1:${port}`;
  server = spawn(process.env.PYTHON || "python3", ["-m", "api.demo", "--port", String(port), "--token", TOKEN], {
    cwd: REPO_ROOT,
    stdio: ["ignore", "inherit", "inherit"],
  });
  await waitUntilUp(`${base}/api/status`, 30_000);
});
after(() => server?.kill());

test("only allowed calls map to requests", () => {
  assert.deepEqual(buildRequest({ kind: "status" }), { method: "GET", path: "/api/status" });
  assert.equal(buildRequest({ kind: "closePosition", id: 3 }).path, "/api/positions/3/close");
  assert.equal(
    buildRequest({ kind: "candles", symbol: "BTC/USDT", timeframe: "1h", limit: 5000 }).path,
    "/api/candles?symbol=BTC%2FUSDT&timeframe=1h&limit=1000",
  );
  assert.throws(() => buildRequest({ kind: "openOrder" }));
  assert.throws(() => buildRequest({ kind: "closePosition", id: -1 }));
  assert.equal(buildRequest({ kind: "command", id: 4 }).path, "/api/commands/4");
  assert.throws(() => buildRequest({ kind: "command", id: 0 }));
  assert.equal(buildRequest({ kind: "logs", limit: 5000 }).path, "/api/logs?limit=1000");
  assert.throws(() => buildRequest({ kind: "updateSetting", key: "../x", value: 1 }));
});

test("mode switching keys cannot be written", () => {
  for (const key of ["paper_trading", "live_trading", "mode", "trading_mode", "api_key"]) {
    assert.throws(() => buildRequest({ kind: "updateSetting", key, value: false }), key);
  }
  assert.equal(buildRequest({ kind: "updateSetting", key: "rsi_period", value: 10 }).method, "PUT");
});

test("base url normalisation", () => {
  assert.equal(normaliseBaseUrl("127.0.0.1:8000/"), "http://127.0.0.1:8000");
  assert.equal(normaliseBaseUrl("https://bot.example/api/"), "https://bot.example");
  assert.equal(wsUrl("https://bot.example", "a b"), "wss://bot.example/api/ws?token=a+b");
});

test("client talks to the real API", async () => {
  const unauth = await performCall(base, "wrong", { kind: "status" });
  assert.equal(unauth.ok, false);
  assert.equal(unauth.status, 401);

  const status = await performCall(base, TOKEN, { kind: "status" });
  assert.ok(status.ok);
  assert.equal(status.data.mode, "paper");
  assert.equal(status.data.bot_running, true);
  assert.equal(typeof status.data.entries_halted_by_daily_limit, "boolean");

  const positions = await performCall(base, TOKEN, { kind: "positions" });
  assert.ok(positions.ok && positions.data.positions.length > 0);
  const pos = positions.data.positions[0];
  for (const key of ["current_price", "unrealized_pnl", "trailing_active", "close_pending", "initial_stop"]) {
    assert.ok(key in pos, key);
  }

  const candles = await performCall(base, TOKEN, { kind: "candles", symbol: "BTC/USDT", timeframe: "1h", limit: 50 });
  assert.ok(candles.ok);
  assert.equal(candles.data.candles.length, 50);
  assert.deepEqual(Object.keys(candles.data.candles[0]).sort(), ["c", "h", "l", "o", "t", "v"]);

  const trades = await performCall(base, TOKEN, { kind: "trades", limit: 5 });
  assert.ok(trades.ok && trades.data.trades.length > 0 && "exit_reason" in trades.data.trades[0]);

  const pnl = await performCall(base, TOKEN, { kind: "pnl" });
  assert.ok(pnl.ok && typeof pnl.data.profit_factor_infinite === "boolean");

  const logs = await performCall(base, TOKEN, { kind: "logs", limit: 5000 });
  assert.ok(logs.ok, logs.error); // the limit is clamped to what the API accepts
  assert.ok(logs.data.logs.length > 0);

  const settings = await performCall(base, TOKEN, { kind: "settings" });
  assert.ok(settings.ok && settings.data.settings.find((s) => s.key === "rsi_period").type === "int");
  const bad = await performCall(base, TOKEN, { kind: "updateSetting", key: "rsi_period", value: 0 });
  assert.equal(bad.ok, false);
  assert.equal(bad.status, 422);
  const good = await performCall(base, TOKEN, { kind: "updateSetting", key: "rsi_period", value: 21 });
  assert.ok(good.ok);
  assert.deepEqual(good.data, { key: "rsi_period", value: 21 });
});

test("closing only queues a command that the bot then handles", async () => {
  const before = await performCall(base, TOKEN, { kind: "positions" });
  const id = before.data.positions[0].id;
  const close = await performCall(base, TOKEN, { kind: "closePosition", id });
  assert.ok(close.ok);
  assert.equal(close.data.status, "pending");
  const again = await performCall(base, TOKEN, { kind: "closePosition", id });
  assert.equal(again.data.command_id, close.data.command_id);

  // the demo plays the bot and handles the queue every 2 s
  let cmd;
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 250));
    cmd = await performCall(base, TOKEN, { kind: "command", id: close.data.command_id });
    if (cmd.data.status !== "pending") break;
  }
  assert.equal(cmd.data.status, "done");
  const afterClose = await performCall(base, TOKEN, { kind: "positions" });
  assert.ok(!afterClose.data.positions.some((p) => p.id === id));
});

test("unreachable server gives a readable error", async () => {
  const res = await performCall("http://127.0.0.1:9", TOKEN, { kind: "status" });
  assert.equal(res.ok, false);
  assert.equal(res.status, 0);
});

test("websocket pushes status and positions and refuses a wrong token", async () => {
  const rejected = new WebSocket(wsUrl(base, "wrong"));
  const code = await new Promise((resolve) => {
    rejected.on("close", (c) => resolve(c));
    rejected.on("error", () => undefined);
  });
  assert.notEqual(code, 1000);

  const ws = new WebSocket(wsUrl(base, TOKEN));
  const types = new Set();
  await new Promise((resolve, reject) => {
    ws.on("message", (raw) => {
      types.add(JSON.parse(raw.toString()).type);
      if (types.has("status") && types.has("positions")) resolve();
    });
    ws.on("error", reject);
  });
  ws.close();
});
