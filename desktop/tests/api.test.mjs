// Runs against the compiled main-process code (npm run build first; `npm test` does it).
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createRequire } from "node:module";
import WebSocket from "ws";
import { startMockServer } from "../mock/server.mjs";

const require = createRequire(import.meta.url);
const { buildRequest, normaliseBaseUrl, wsUrl } = require("../dist-electron/electron/apiRoutes.js");
const { performCall } = require("../dist-electron/electron/apiClient.js");

const TOKEN = "test-token";
let mock;
let base;

before(async () => {
  mock = await startMockServer({ port: 0, token: TOKEN, tickMs: 50 });
  base = `http://127.0.0.1:${mock.port}`;
});
after(() => mock.close());

test("only allowed calls map to requests", () => {
  assert.deepEqual(buildRequest({ kind: "status" }), { method: "GET", path: "/api/status" });
  assert.equal(buildRequest({ kind: "closePosition", id: 3 }).path, "/api/positions/3/close");
  assert.equal(
    buildRequest({ kind: "candles", symbol: "BTC/USDT", timeframe: "1h", limit: 5000 }).path,
    "/api/candles?symbol=BTC%2FUSDT&timeframe=1h&limit=1000",
  );
  assert.throws(() => buildRequest({ kind: "openOrder" }));
  assert.throws(() => buildRequest({ kind: "closePosition", id: -1 }));
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

test("client talks to the mock API", async () => {
  const unauth = await performCall(base, "wrong", { kind: "status" });
  assert.equal(unauth.ok, false);
  assert.equal(unauth.status, 401);

  const status = await performCall(base, TOKEN, { kind: "status" });
  assert.ok(status.ok);
  assert.equal(status.data.mode, "paper");

  const positions = await performCall(base, TOKEN, { kind: "positions" });
  assert.ok(positions.ok && positions.data.length > 0);

  const candles = await performCall(base, TOKEN, { kind: "candles", symbol: "BTC/USDT", timeframe: "1h", limit: 50 });
  assert.ok(candles.ok);
  assert.equal(candles.data.length, 50);

  const bad = await performCall(base, TOKEN, { kind: "updateSetting", key: "rsi_period", value: 1.5 });
  assert.equal(bad.ok, false);
  const good = await performCall(base, TOKEN, { kind: "updateSetting", key: "rsi_period", value: 21 });
  assert.ok(good.ok);
  assert.equal(good.data.value, 21);

  const close = await performCall(base, TOKEN, { kind: "closePosition", id: positions.data[0].id });
  assert.ok(close.ok);
  assert.equal(close.data.status, "pending");
});

test("unreachable server gives a readable error", async () => {
  const res = await performCall("http://127.0.0.1:9", TOKEN, { kind: "status" });
  assert.equal(res.ok, false);
  assert.equal(res.status, 0);
});

test("websocket pushes status and positions", async () => {
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
