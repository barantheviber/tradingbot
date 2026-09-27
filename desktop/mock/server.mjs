// Development mock of the bot's HTTP API contract (see ../README.md).
// Run: npm run mock   ->  http://127.0.0.1:8765, token "dev-token".
// Fake data only; it never talks to an exchange.

import http from "node:http";
import { pathToFileURL } from "node:url";
import { WebSocketServer } from "ws";

const DEFAULT_PORT = Number(process.env.MOCK_PORT || 8765);
const DEFAULT_TOKEN = process.env.MOCK_TOKEN || "dev-token";

const TF_MS = { "1m": 60e3, "5m": 300e3, "15m": 900e3, "1h": 3600e3, "4h": 14400e3, "1d": 86400e3 };

function nowIso() {
  return new Date().toISOString();
}

function makeState() {
  const settings = [
    ["trading_enabled", true, "Yeni pozisyon açılışına izin ver (kill switch)."],
    ["ema_trend_period", 200, "Trend filtresi EMA periyodu."],
    ["rsi_period", 14, "RSI periyodu."],
    ["rsi_long_min", 45.0, "Long için RSI alt sınırı."],
    ["rsi_long_max", 70.0, "Long için RSI üst sınırı (aşırı alım filtresi)."],
    ["macd_fast", 12, "MACD hızlı EMA periyodu."],
    ["macd_slow", 26, "MACD yavaş EMA periyodu."],
    ["volume_factor", 1.2, "Hacim, ortalamanın en az kaç katı olmalı."],
    ["risk_per_trade_pct", 1.0, "İşlem başına riske edilen özsermaye yüzdesi."],
    ["atr_sl_multiplier", 1.5, "Stop-loss mesafesi = ATR x bu katsayı."],
    ["risk_reward_ratio", 2.0, "Take-profit mesafesi = stop mesafesi x bu oran."],
    ["trailing_enabled", true, "Trailing stop aktif."],
    ["daily_loss_limit_pct", 5.0, "Günlük zarar bu yüzdeyi aşarsa UTC gece yarısına kadar yeni pozisyon açma."],
    ["max_open_positions", 3, "Maksimum eşzamanlı açık pozisyon."],
  ].map(([key, value, description]) => ({ key, value, description, updated_at: nowIso() }));

  const prices = { "BTC/USDT": 64000, "ETH/USDT": 3100 };
  const positions = [
    {
      id: 7, symbol: "BTC/USDT", side: "long", quantity: 0.015, entry_price: 63210.5,
      stop_loss: 62400, take_profit: 64830, initial_stop: 62100, trailing_stop: 62400,
      opened_at: new Date(Date.now() - 5 * 3600e3).toISOString(), mode: "paper",
    },
    {
      id: 8, symbol: "ETH/USDT", side: "long", quantity: 0.4, entry_price: 3125.2,
      stop_loss: 3060, take_profit: 3255.6, initial_stop: 3060, trailing_stop: null,
      opened_at: new Date(Date.now() - 2 * 3600e3).toISOString(), mode: "paper",
    },
  ];
  const trades = [];
  for (let i = 0; i < 12; i++) {
    const win = i % 3 !== 0;
    trades.push({
      id: 100 + i, position_id: i + 1, symbol: i % 2 ? "ETH/USDT" : "BTC/USDT", side: "sell", action: "close",
      quantity: i % 2 ? 0.5 : 0.01, price: i % 2 ? 3000 + i * 10 : 60000 + i * 150, fee: 0.6,
      pnl: win ? 12 + i : -(8 + i), reason: win ? "take_profit" : "stop_loss", mode: "paper",
      timestamp: new Date(Date.now() - (12 - i) * 6 * 3600e3).toISOString(),
    });
  }
  const logs = [];
  let logId = 1;
  const addLog = (level, category, message, symbol = null) => {
    const line = { id: logId++, timestamp: nowIso(), level, category, symbol, message };
    logs.push(line);
    if (logs.length > 2000) logs.shift();
    return line;
  };
  addLog("INFO", "engine", "Bot başlatıldı (paper modu, mock veri)");
  addLog("INFO", "signal", "Kapanan mum işlendi: trend yukarı, 2/3 teyit, giriş yok", "BTC/USDT");
  return { settings, prices, positions, trades, logs, addLog, closing: new Set(), nextCommand: 1 };
}

function candles(state, symbol, timeframe, limit) {
  const step = TF_MS[timeframe] || TF_MS["1h"];
  const last = Math.floor(Date.now() / step) * step;
  let seed = [...symbol].reduce((a, c) => a + c.charCodeAt(0), 0);
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const out = [];
  let price = (state.prices[symbol] || 100) * 0.95;
  for (let i = limit - 1; i >= 0; i--) {
    const open = price;
    const close = open * (1 + (rand() - 0.49) * 0.012);
    const high = Math.max(open, close) * (1 + rand() * 0.004);
    const low = Math.min(open, close) * (1 - rand() * 0.004);
    out.push([last - i * step, open, high, low, close, 100 + rand() * 900]);
    price = close;
  }
  // rescale so the latest close matches the live mock price
  const k = (state.prices[symbol] || price) / price;
  return out.map(([t, o, h, l, c, v]) => [t, o * k, h * k, l * k, c * k, v]);
}

function withPnl(state) {
  return state.positions.map((p) => {
    const last = state.prices[p.symbol];
    const dir = p.side === "long" ? 1 : -1;
    return {
      ...p, last_price: last, unrealized_pnl: (last - p.entry_price) * p.quantity * dir,
      close_pending: state.closing.has(p.id),
    };
  });
}

function status(state) {
  const today = new Date().toISOString().slice(0, 10);
  const realized = state.trades.filter((t) => t.timestamp.startsWith(today)).reduce((a, t) => a + (t.pnl || 0), 0);
  const unrealized = withPnl(state).reduce((a, p) => a + p.unrealized_pnl, 0);
  return {
    mode: "paper", exchange: "binance", symbols: Object.keys(state.prices), timeframe: "1h", running: true,
    today_pnl: realized + unrealized, entries_halted: false, equity: 10000 + realized + unrealized,
    last_candle_at: new Date(Math.floor(Date.now() / 3600e3) * 3600e3).toISOString(), server_time: nowIso(),
  };
}

function pnl(state) {
  const pnls = state.trades.map((t) => t.pnl).filter((x) => x !== null);
  const wins = pnls.filter((x) => x > 0);
  const losses = pnls.filter((x) => x <= 0);
  const gw = wins.reduce((a, b) => a + b, 0);
  const gl = -losses.reduce((a, b) => a + b, 0);
  let eq = 0, peak = 0, dd = 0;
  for (const x of pnls) { eq += x; peak = Math.max(peak, eq); dd = Math.max(dd, peak - eq); }
  return {
    trades: pnls.length, wins: wins.length, losses: losses.length,
    win_rate_pct: pnls.length ? (wins.length / pnls.length) * 100 : 0, total_pnl: gw - gl,
    avg_win: wins.length ? gw / wins.length : 0, avg_loss: losses.length ? -gl / losses.length : 0,
    profit_factor: gl > 0 ? gw / gl : null, expectancy: pnls.length ? (gw - gl) / pnls.length : 0,
    max_drawdown: dd, max_drawdown_pct: (dd / 10000) * 100, fees: state.trades.reduce((a, t) => a + t.fee, 0),
  };
}

function coerce(value, current) {
  switch (typeof current) {
    case "boolean":
      if (typeof value === "boolean") return value;
      if (["true", "1", "yes"].includes(String(value).toLowerCase())) return true;
      if (["false", "0", "no"].includes(String(value).toLowerCase())) return false;
      throw new Error(`boolean bekleniyordu: ${value}`);
    case "number": {
      const n = Number(value);
      if (!Number.isFinite(n)) throw new Error(`sayı bekleniyordu: ${value}`);
      if (Number.isInteger(current) && !Number.isInteger(n)) throw new Error(`tam sayı bekleniyordu: ${value}`);
      return n;
    }
    default:
      return String(value);
  }
}

export function startMockServer({ port = DEFAULT_PORT, token = DEFAULT_TOKEN, tickMs = 2000 } = {}) {
  const state = makeState();
  const clients = new Set();
  const broadcast = (msg) => {
    const raw = JSON.stringify(msg);
    for (const c of clients) if (c.readyState === 1) c.send(raw);
  };

  const send = (res, code, body) => {
    res.writeHead(code, { "Content-Type": "application/json" });
    res.end(JSON.stringify(body));
  };

  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://localhost");
    if (req.headers.authorization !== `Bearer ${token}`) return send(res, 401, { detail: "unauthorized" });
    const p = url.pathname;
    const limit = Math.max(1, Math.min(1000, Number(url.searchParams.get("limit") || 100)));

    if (req.method === "GET" && p === "/api/status") return send(res, 200, status(state));
    if (req.method === "GET" && p === "/api/positions") return send(res, 200, withPnl(state));
    if (req.method === "GET" && p === "/api/trades") return send(res, 200, state.trades.slice(-limit).reverse());
    if (req.method === "GET" && p === "/api/pnl") return send(res, 200, pnl(state));
    if (req.method === "GET" && p === "/api/settings") return send(res, 200, state.settings);
    if (req.method === "GET" && p === "/api/logs") return send(res, 200, state.logs.slice(-limit));
    if (req.method === "GET" && p === "/api/candles") {
      const symbol = url.searchParams.get("symbol") || "BTC/USDT";
      return send(res, 200, candles(state, symbol, url.searchParams.get("timeframe") || "1h", limit));
    }

    let m = p.match(/^\/api\/positions\/(\d+)\/close$/);
    if (req.method === "POST" && m) {
      const id = Number(m[1]);
      if (!state.positions.some((x) => x.id === id)) return send(res, 404, { detail: "position not found" });
      const commandId = state.nextCommand++;
      state.closing.add(id);
      broadcast({ type: "log", data: state.addLog("INFO", "command", `Kapatma komutu kuyruğa alındı (pozisyon ${id})`) });
      broadcast({ type: "positions", data: withPnl(state) });
      // the "bot" picks up the queued command on its next poll
      setTimeout(() => {
        const idx = state.positions.findIndex((x) => x.id === id);
        if (idx < 0) return;
        const pos = withPnl(state)[idx];
        state.positions.splice(idx, 1);
        state.closing.delete(id);
        state.trades.push({
          id: 1000 + commandId, position_id: id, symbol: pos.symbol, side: pos.side === "long" ? "sell" : "buy",
          action: "close", quantity: pos.quantity, price: pos.last_price, fee: 0.5, pnl: pos.unrealized_pnl - 0.5,
          reason: "manual", mode: "paper", timestamp: nowIso(),
        });
        broadcast({ type: "log", data: state.addLog("INFO", "execution", `Pozisyon ${id} manuel kapatıldı`, pos.symbol) });
        broadcast({ type: "positions", data: withPnl(state) });
        broadcast({ type: "status", data: status(state) });
      }, 1500);
      return send(res, 202, { command_id: commandId, status: "pending" });
    }

    m = p.match(/^\/api\/settings\/([a-z0-9_]+)$/);
    if (req.method === "PUT" && m) {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        const setting = state.settings.find((s) => s.key === m[1]);
        if (!setting) return send(res, 404, { detail: "unknown setting" });
        try {
          setting.value = coerce(JSON.parse(body || "{}").value, setting.value);
          setting.updated_at = nowIso();
          broadcast({ type: "log", data: state.addLog("INFO", "settings", `Ayar güncellendi: ${setting.key}=${setting.value}`) });
          send(res, 200, setting);
        } catch (err) {
          send(res, 422, { detail: err.message });
        }
      });
      return;
    }
    send(res, 404, { detail: "not found" });
  });

  const wss = new WebSocketServer({ noServer: true });
  server.on("upgrade", (req, socket, head) => {
    const url = new URL(req.url, "http://localhost");
    if (url.pathname !== "/api/ws" || url.searchParams.get("token") !== token) {
      socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
      socket.destroy();
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws) => {
      clients.add(ws);
      ws.on("close", () => clients.delete(ws));
      ws.send(JSON.stringify({ type: "status", data: status(state) }));
      ws.send(JSON.stringify({ type: "positions", data: withPnl(state) }));
    });
  });

  const tick = setInterval(() => {
    for (const s of Object.keys(state.prices)) state.prices[s] *= 1 + (Math.random() - 0.5) * 0.002;
    broadcast({ type: "positions", data: withPnl(state) });
    broadcast({ type: "status", data: status(state) });
  }, tickMs);

  return new Promise((resolve) => {
    server.listen(port, "127.0.0.1", () => {
      resolve({
        port: server.address().port,
        close: () => {
          clearInterval(tick);
          for (const c of clients) c.terminate();
          wss.close();
          return new Promise((r) => server.close(r));
        },
      });
    });
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  startMockServer().then(({ port }) => {
    console.log(`Mock API: http://127.0.0.1:${port}  token: ${DEFAULT_TOKEN}`);
  });
}
