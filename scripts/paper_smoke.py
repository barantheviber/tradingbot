"""Run the whole bot in paper mode against a real exchange's public market data.

No API keys are used. The bot is started the way the Windows and Android apps
start it (``LocalRuntime`` -> ``main.build_engine``, with the HTTP API on
127.0.0.1), and the run checks, in order:

1. start: markets load, the clock syncs, (paged) closed candles are fetched and
   evaluated for every symbol, prices arrive and the API reports a running bot;
   with ``--wait-new-candle`` it also waits for the next candle to close;
2. a paper entry at the real price and ATR, through the bot's own entry path
   (risk sizing, exposure cap, fees, slippage), lands on the exchange's amount
   step, and an order below the exchange minimum is refused;
3. restart on the same database: the position is restored and priced, and
   equity includes it;
4. the position is closed through the API, as the apps do, with fees and
   slippage booked;
5. no ERROR or CRITICAL event was logged during the run.

    python scripts/paper_smoke.py --exchange kraken --symbols BTC/USDT,ETH/USDT
    python scripts/paper_smoke.py --exchange binance --spot-markets-only \
        --replace-host api.binance.com=data-api.binance.vision

Exits 1 with a list of problems. Writes a Markdown summary to
``$GITHUB_STEP_SUMMARY`` when that is set.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STARTING_BALANCE = 10_000.0


class SmokeFailure(Exception):
    pass


class Report:
    def __init__(self, title: str):
        self.title = title
        self.lines: List[str] = []
        self.problems: List[str] = []

    def ok(self, message: str) -> None:
        print(f"  ok    {message}", flush=True)
        self.lines.append(f"- ✅ {message}")

    def fail(self, message: str) -> None:
        print(f"  FAIL  {message}", flush=True)
        self.lines.append(f"- ❌ {message}")
        self.problems.append(message)

    def note(self, message: str) -> None:
        print(f"  note  {message}", flush=True)
        self.lines.append(f"- {message}")

    def check(self, condition: bool, message: str, detail: str = "") -> bool:
        if condition:
            self.ok(message)
        else:
            self.fail(f"{message}{': ' + detail if detail else ''}")
        return condition

    def markdown(self) -> str:
        verdict = "passed" if not self.problems else f"{len(self.problems)} problem(s)"
        return "\n".join([f"### {self.title}: {verdict}", "", *self.lines, ""])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(predicate: Callable[[], Any], timeout: float, what: str, every: float = 1.0) -> Any:
    deadline = time.monotonic() + timeout
    last_exc: Optional[BaseException] = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:  # e.g. the API is not listening yet
            last_exc = exc
        time.sleep(every)
    raise SmokeFailure(f"timed out after {timeout:.0f}s waiting for {what}"
                       + (f" (last error: {type(last_exc).__name__}: {last_exc})" if last_exc else ""))


class Api:
    def __init__(self, port: int, token: str):
        self.base = f"http://127.0.0.1:{port}"
        self.token = token

    def request(self, method: str, path: str) -> Any:
        req = urllib.request.Request(self.base + path, method=method,
                                     headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str) -> Any:
        return self.request("POST", path)


def reroute_public_hosts(replace: List[str], hostname: str, spot_markets_only: bool) -> None:
    """Point the exchange client at other hosts of the same exchange.

    GitHub's runners are in the US, where e.g. api.binance.com answers 451;
    data-api.binance.vision serves the same public spot endpoints. Used for
    CI only; the bot itself always talks to the exchange's default hosts."""
    import exchange_client

    original = exchange_client.ExchangeClient.__init__
    pairs = [item.split("=", 1) for item in replace]

    def rewrite(value):
        if isinstance(value, str):
            for old, new in pairs:
                value = value.replace(old, new)
            return value
        if isinstance(value, dict):
            return {k: rewrite(v) for k, v in value.items()}
        return value

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        ex = self.exchange
        if pairs:
            ex.urls["api"] = rewrite(ex.urls["api"])
        if hostname:
            ex.hostname = hostname
        if spot_markets_only:  # skip futures markets whose hosts are blocked too
            ex.options["fetchMarkets"] = {**dict(ex.options.get("fetchMarkets") or {}), "types": ["spot"]}

    exchange_client.ExchangeClient.__init__ = init


def configure_env(args, workdir: Path, port: int, token: str) -> Path:
    for key in ("API_KEY", "API_SECRET", "API_PASSWORD", "LIVE_TRADING_CONFIRM", "USE_TESTNET"):
        os.environ.pop(key, None)
    os.environ.update({
        "PAPER_TRADING": "true",
        "EXCHANGE_ID": args.exchange,
        "MARKET_TYPE": args.market_type,
        "SYMBOLS": args.symbols,
        "TIMEFRAME": args.timeframe,
        "POLL_INTERVAL_SEC": str(args.poll),
        "DB_PATH": str(workdir / "bot.db"),
        "LOG_DIR": str(args.log_dir or workdir / "logs"),
        "LOG_LEVEL": "INFO",
        "PAPER_STARTING_BALANCE": str(STARTING_BALANCE),
        "API_PORT": str(port),
        "API_TOKEN": token,
    })
    return workdir / "none.env"  # no .env file: everything comes from the environment


def bad_events(state, after_id: int = 0) -> List[Dict[str, Any]]:
    return [e for e in state.get_events(limit=1000, after_id=after_id) if e["level"] in ("ERROR", "CRITICAL")]


def run(args) -> Report:
    report = Report(f"{args.exchange} {args.market_type} {args.symbols} {args.timeframe}")
    if args.replace_host or args.hostname or args.spot_markets_only:
        reroute_public_hosts(args.replace_host, args.hostname, args.spot_markets_only)

    from config import load_config
    from local_runtime import LocalRuntime
    from main import build_engine
    from state_manager import StateManager

    workdir = Path(args.workdir or tempfile.mkdtemp(prefix="paper-smoke-"))
    workdir.mkdir(parents=True, exist_ok=True)
    port, token = free_port(), secrets.token_hex(16)
    env_file = str(configure_env(args, workdir, port, token))
    api = Api(port, token)
    config = load_config(env_file)
    symbols = config.symbols

    # ------------------------------------------------------------- 1. start
    print(f"[1/4] starting the bot (paper, {config.exchange_id}, {symbols}, {config.timeframe})", flush=True)
    t0 = time.time()
    runtime = LocalRuntime(env_file)
    runtime.start()
    watch = StateManager(config.db_path)
    try:
        def first_tick():
            if not runtime.running:
                raise SmokeFailure(f"bot stopped: {runtime.status().get('error')}")
            hb = watch.get_state("heartbeat") or {}
            return hb if hb.get("ts", 0) > t0 and set(symbols) <= set(hb.get("prices") or {}) else None

        try:
            hb = wait_until(first_tick, args.start_timeout, "the first loop with prices for every symbol")
        except SmokeFailure as exc:
            report.fail(str(exc))
            for e in bad_events(watch)[:10]:
                report.note(f"event: {e['level']} {e['message']}")
            return report
        report.ok(f"first loop done in {time.time() - t0:.0f}s; prices {hb['prices']}")

        status = wait_until(lambda: (lambda s: s if s.get("bot_running") else None)(api.get("/api/status")),
                            30, "the API to report a running bot")
        report.check(status["mode"] == "paper", "API reports paper mode", str(status["mode"]))
        report.check(status["equity"] is not None and abs(status["equity"] - STARTING_BALANCE) < 1e-6,
                     "equity equals the paper starting balance", str(status["equity"]))

        import ccxt

        tf_ms = int(ccxt.Exchange.parse_timeframe(config.timeframe) * 1000)
        now_ms = time.time() * 1000
        for symbol in symbols:
            key = f"last_candle:{symbol}:{config.timeframe}"
            last = watch.get_state(key)
            if not report.check(bool(last), f"{symbol}: a closed candle was evaluated"):
                continue
            close_ms = int(last) + tf_ms
            report.check(close_ms <= now_ms + 5_000 and now_ms - close_ms < 2 * tf_ms + 120_000,
                         f"{symbol}: the evaluated candle is the latest closed one",
                         f"closed {(now_ms - close_ms) / 60000:.1f} min ago")
            short = watch.get_state(f"warmup_short:{symbol}:{config.timeframe}")
            report.check(not short, f"{symbol}: enough history for the strategy warm-up", str(short))
        signals = watch.get_events(limit=200, category="signal")
        report.note(f"signals logged: {', '.join(e['message'] for e in signals[:len(symbols)])}")

        candles = api.get(f"/api/candles?symbol={urllib.request.quote(symbols[0])}&limit=50")["candles"]
        report.check(len(candles) >= 40 and now_ms - candles[-1]["t"] < 2 * tf_ms + 120_000,
                     f"API chart candles for {symbols[0]} are current", f"{len(candles)} candles")

        if args.wait_new_candle:
            first = {s: int(watch.get_state(f"last_candle:{s}:{config.timeframe}") or 0) for s in symbols}
            wait_s = (max(first.values()) + 2 * tf_ms) / 1000 - time.time() + 3 * args.poll + 30
            try:
                wait_until(lambda: all(int(watch.get_state(f"last_candle:{s}:{config.timeframe}") or 0) > first[s]
                                       for s in symbols), max(wait_s, 30), "the next candle to close and be evaluated")
                report.ok("the next closed candle was picked up while running")
            except SmokeFailure as exc:
                report.fail(str(exc))

        if args.run_seconds:
            time.sleep(args.run_seconds)
    finally:
        runtime.stop()
    report.check(not runtime.running, "bot and API stopped on request")
    report.check((watch.get_state("bot_status") or {}).get("status") == "stopped", "bot status saved as stopped")

    # ------------------------------------------------- 2. paper orders
    print("[2/4] paper entries at the real price, sized by the risk manager", flush=True)
    from strategy import Signal, StrategyParams, compute_indicators

    state = StateManager(config.db_path)
    engine = build_engine(config, state)
    engine.exchange.load_markets()
    settings = state.get_all_settings()
    params = StrategyParams.from_settings(settings)
    slip = config.paper_slippage_bps / 10_000
    for symbol in symbols:
        price = engine.exchange.fetch_last_price(symbol)
        engine._last_prices[symbol] = price
        size = engine.executor._contract_size(symbol)
        limits = engine.exchange.market_limits(symbol)
        dust_cost = 0.5 * float(limits.get("min_cost") or 0) or None
        if dust_cost is None and limits.get("min_amount"):
            dust_cost = 0.5 * float(limits["min_amount"]) * size * price
        if dust_cost:
            dust = engine.executor.open_position(symbol, "long", dust_cost / price, price, price * 0.5, price * 2.0,
                                                 price * 0.01, reason="smoke test dust")
            report.check(dust is None, f"{symbol}: an order below the exchange minimum ({dust_cost:.4g}) is refused")
        else:
            report.note(f"{symbol}: the exchange states no minimum order size")

        df = engine.exchange.fetch_closed_ohlcv(symbol, config.timeframe, max(config.ohlcv_limit, params.warmup + 50))
        atr = float(compute_indicators(df, params)["atr"].iloc[-1])
        if any(p["symbol"] == symbol for p in engine.executor.open_positions()):
            report.note(f"{symbol}: the bot already holds a position (opened on a real signal)")
            continue
        # the bot's own entry path with a long signal at the real price and ATR
        engine._try_entry(symbol, Signal(action="long", close=price, atr=atr), price, settings)
        pos = next((p for p in engine.executor.open_positions() if p["symbol"] == symbol), None)
        if not report.check(pos is not None, f"{symbol}: paper long at {price} (ATR {atr:.6g}) accepted"):
            for e in state.get_events(limit=3, category="decision"):
                report.note(f"decision: {e['message']}")
            continue
        units = float(engine.exchange.amount_to_precision(symbol, pos["quantity"] / size))
        report.check(pos["quantity"] > 0 and math.isclose(units * size, pos["quantity"], rel_tol=1e-9),
                     f"{symbol}: quantity {pos['quantity']:.8g} is on the exchange step"
                     + (f" ({units:g} contracts of {size:g})" if size != 1 else ""))
        notional = pos["quantity"] * pos["entry_price"]
        cap = STARTING_BALANCE * float(settings["max_symbol_exposure_pct"]) / 100
        report.check(notional <= cap * 1.01, f"{symbol}: notional {notional:.2f} within the exposure cap {cap:.0f}")
        risk = pos["quantity"] * (pos["entry_price"] - pos["stop_loss"]) + pos["fees"]
        budget = STARTING_BALANCE * float(settings["risk_per_trade_pct"]) / 100
        report.check(0 < risk <= budget * 1.01, f"{symbol}: loss at the stop {risk:.2f} within the risk budget "
                                                f"{budget:.0f}")
        report.check(math.isclose(pos["entry_price"], price * (1 + slip), rel_tol=1e-9),
                     f"{symbol}: entry includes {config.paper_slippage_bps} bps slippage")
        report.check(math.isclose(pos["fees"], notional * config.paper_fee_rate, rel_tol=1e-6),
                     f"{symbol}: entry fee booked")
    opened = {p["id"]: p for p in engine.executor.open_positions()}
    state.close()
    if not opened:
        return report

    # ------------------------------------------------------ 3. restart
    print("[3/4] restart on the same database", flush=True)
    t1 = time.time()
    runtime = LocalRuntime(env_file)
    runtime.start()
    try:
        try:
            wait_until(lambda: (watch.get_state("heartbeat") or {}).get("ts", 0) > t1 and
                       api.get("/api/status").get("bot_running"), args.start_timeout, "the restarted bot's first loop")
        except SmokeFailure as exc:
            report.fail(str(exc))
            return report
        for pid, pos in list(opened.items()):
            now = watch.get_position(pid)
            if now["status"] != "open":  # a real stop or target was hit in between: fine, but nothing to close
                report.note(f"#{pid} {pos['symbol']} closed by the bot on restart ({now['exit_reason']})")
                opened.pop(pid)
        positions = {p["id"]: p for p in api.get("/api/positions")["positions"]}
        report.check(set(positions) == set(opened), "open positions restored after restart", str(sorted(positions)))
        for pid, pos in positions.items():
            report.check(pos["current_price"] is not None and pos["unrealized_pnl"] is not None,
                         f"{pos['symbol']}: restored position is priced", f"price {pos['current_price']}")
        status = api.get("/api/status")
        hb = watch.get_state("heartbeat") or {}
        expected = STARTING_BALANCE + watch.realized_pnl("paper") + sum(
            (hb["prices"][p["symbol"]] - p["entry_price"]) * p["quantity"] - p["fees"] for p in opened.values())
        report.check(status["equity"] is not None and abs(status["equity"] - expected) < 0.01,
                     "equity includes the open positions", f"{status['equity']} vs {expected:.2f}")

        # ------------------------------------------------ 4. close via API
        print("[4/4] closing through the API", flush=True)
        for pid, pos in opened.items():
            cmd = api.post(f"/api/positions/{pid}/close")
            try:
                done = wait_until(lambda: (lambda c: c if c["status"] != "pending" else None)(
                    api.get(f"/api/commands/{cmd['command_id']}")), 60, f"the close of {pos['symbol']}")
            except SmokeFailure as exc:
                report.fail(str(exc))
                continue
            report.check(done["status"] == "done", f"{pos['symbol']}: close command done", str(done.get("note")))
        trades = {t["id"]: t for t in api.get("/api/trades")["trades"]}
        for pid, pos in opened.items():
            trade = trades.get(pid)
            if not report.check(trade is not None, f"{pos['symbol']}: closed trade listed"):
                continue
            gross = (trade["exit_price"] - pos["entry_price"]) * pos["quantity"]
            report.check(trade["pnl"] is not None and trade["pnl"] < gross and trade["exit_reason"] == "manual",
                         f"{pos['symbol']}: PnL {trade['pnl']:.4f} is after fees (gross {gross:.4f})")
        report.check(api.get("/api/status")["open_positions"] == 0, "no open positions left")
    finally:
        runtime.stop()

    errors = bad_events(watch)
    report.check(not errors, "no ERROR or CRITICAL events during the run",
                 "; ".join(f"{e['level']} {e['message']}" for e in errors[:5]))
    warnings = [e["message"] for e in watch.get_events(limit=1000) if e["level"] == "WARNING"]
    if warnings:
        report.note(f"warnings: {'; '.join(warnings[:5])}")
    return report


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--exchange", default="binance")
    p.add_argument("--market-type", default="spot")
    p.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    p.add_argument("--timeframe", default="4h")
    p.add_argument("--poll", type=int, default=5, help="POLL_INTERVAL_SEC for the run")
    p.add_argument("--wait-new-candle", action="store_true", help="also wait for the next candle to close")
    p.add_argument("--run-seconds", type=int, default=0, help="keep the first run going this long")
    p.add_argument("--start-timeout", type=float, default=240)
    p.add_argument("--replace-host", action="append", default=[], metavar="OLD=NEW",
                   help="rewrite API hosts, e.g. api.binance.com=data-api.binance.vision (for US runners)")
    p.add_argument("--hostname", default="", help="set the ccxt hostname, e.g. bytick.com for Bybit")
    p.add_argument("--spot-markets-only", action="store_true", help="load spot markets only")
    p.add_argument("--workdir", default="")
    p.add_argument("--log-dir", default="")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        report = run(args)
    except Exception as exc:  # report, never hide, an unexpected crash
        report = Report(f"{args.exchange} {args.market_type} {args.symbols} {args.timeframe}")
        report.fail(f"crashed: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report.markdown() + "\n")
    print(report.markdown())
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
