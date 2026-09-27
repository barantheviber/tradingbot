"""FastAPI app for the mobile and desktop clients.

Read-mostly JSON API over the bot's SQLite state. Every route needs
``Authorization: Bearer <API_TOKEN>`` (the WebSocket takes ``?token=``).
The only writes are editing live settings (validated) and queueing a close
command that the running bot executes. No route returns exchange API keys,
switches paper/live, or opens orders.
"""

from __future__ import annotations

import asyncio
import hmac
import re
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from api.service import BotReadModel
from api.validation import UnknownSettingError, validate_setting
from config import Config
from logging_setup import get_logger
from state_manager import StateManager

log = get_logger("api")

API_VERSION = "1"
_TIMEFRAME_RE = re.compile(r"^\d{1,3}[smhdwM]$")
CANDLE_CACHE_SEC = 15.0
WS_POLL_SEC = 1.0
WS_PING_SEC = 20.0


def _token_ok(expected: str, given: Optional[str]) -> bool:
    return bool(expected) and bool(given) and hmac.compare_digest(expected.encode(), given.encode())


class CandleSource:
    """Public-data exchange client (never gets API keys) with a short cache."""

    def __init__(self, config: Config, factory: Optional[Callable[[], Any]] = None):
        self._config = config
        self._factory = factory
        self._client = None
        self._lock = threading.Lock()
        self._cache: Dict[Tuple[str, str, int], Tuple[float, list]] = {}

    def _get_client(self):
        if self._client is None:
            if self._factory is not None:
                self._client = self._factory()
            else:
                from exchange_client import ExchangeClient

                self._client = ExchangeClient.from_config(self._config, public_only=True)
                self._client.max_retries = min(self._client.max_retries, 2)
        return self._client

    def get(self, symbol: str, timeframe: str, limit: int) -> list:
        key = (symbol, timeframe, limit)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < CANDLE_CACHE_SEC:
                return hit[1]
            df = self._get_client().fetch_ohlcv(symbol, timeframe, limit)
            rows = [
                {"t": int(r.timestamp), "o": float(r.open), "h": float(r.high), "l": float(r.low),
                 "c": float(r.close), "v": float(r.volume)}
                for r in df.itertuples(index=False)
            ]
            self._cache[key] = (time.time(), rows)
            return rows


def create_app(config: Config, state: StateManager, candle_factory: Optional[Callable[[], Any]] = None) -> FastAPI:
    if not config.api_token:
        raise ValueError("API_TOKEN is empty: set it in .env (python -m api --generate-token)")

    model = BotReadModel(config, state)
    candles = CandleSource(config, candle_factory)
    app = FastAPI(title="tradingbot API", version=API_VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.model = model
    if config.api_cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=config.api_cors_origins, allow_methods=["GET", "POST", "PUT"],
                           allow_headers=["Authorization", "Content-Type"])

    def require_token(request: Request) -> None:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not _token_ok(config.api_token, token.strip()):
            raise HTTPException(status_code=401, detail="invalid or missing token",
                                headers={"WWW-Authenticate": "Bearer"})

    auth = [Depends(require_token)]

    # Sync handlers run in FastAPI's thread pool, so SQLite / ccxt calls never block the event loop.
    @app.get("/api/status", dependencies=auth)
    def get_status() -> Dict[str, Any]:
        return {**model.status(), "api_version": API_VERSION}

    @app.get("/api/positions", dependencies=auth)
    def get_positions() -> Dict[str, Any]:
        return {"positions": model.positions()}

    @app.post("/api/positions/{position_id}/close", dependencies=auth, status_code=202)
    def close_position(position_id: int) -> Dict[str, Any]:
        try:
            return model.request_close(position_id, source="api")
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/commands/{command_id}", dependencies=auth)
    def get_command(command_id: int) -> Dict[str, Any]:
        cmd = model.command(command_id)
        if cmd is None:
            raise HTTPException(status_code=404, detail="command not found")
        return cmd

    @app.get("/api/trades", dependencies=auth)
    def get_trades(limit: int = Query(100, ge=1, le=1000)) -> Dict[str, Any]:
        return {"trades": model.trades(limit)}

    @app.get("/api/pnl", dependencies=auth)
    def get_pnl() -> Dict[str, Any]:
        return model.pnl()

    @app.get("/api/candles", dependencies=auth)
    def get_candles(symbol: Optional[str] = None, timeframe: Optional[str] = None,
                    limit: int = Query(200, ge=10, le=1000)) -> Dict[str, Any]:
        symbol = symbol or config.symbols[0]
        timeframe = timeframe or config.timeframe
        if symbol not in config.symbols:
            raise HTTPException(status_code=400, detail=f"symbol must be one of {config.symbols}")
        if not _TIMEFRAME_RE.match(timeframe):
            raise HTTPException(status_code=400, detail="invalid timeframe")
        try:
            rows = candles.get(symbol, timeframe, limit)
        except Exception as exc:
            log.warning("Candle fetch failed", extra={"symbol": symbol, "error": type(exc).__name__})
            raise HTTPException(status_code=502, detail=f"exchange error: {type(exc).__name__}")
        return {"symbol": symbol, "timeframe": timeframe, "candles": rows}

    @app.get("/api/settings", dependencies=auth)
    def get_settings() -> Dict[str, Any]:
        return {"settings": model.settings()}

    @app.put("/api/settings/{key}", dependencies=auth)
    def put_setting(key: str, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        if "value" not in body:
            raise HTTPException(status_code=422, detail='body must be {"value": ...}')
        try:
            value = validate_setting(key, body["value"], state.get_all_settings())
        except UnknownSettingError:
            raise HTTPException(status_code=404, detail=f"unknown setting {key!r}")
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"{key}: {exc}")
        stored = state.set_setting(key, value)
        state.log_event("INFO", "settings", f"Setting {key} changed from API", data={"key": key, "value": stored})
        return {"key": key, "value": stored}

    @app.get("/api/logs", dependencies=auth)
    def get_logs(limit: int = Query(200, ge=1, le=1000), after_id: int = Query(0, ge=0),
                 category: Optional[str] = None) -> Dict[str, Any]:
        return {"logs": model.logs(limit, after_id, category)}

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket) -> None:
        token = websocket.query_params.get("token")
        if not token:
            scheme, _, value = websocket.headers.get("authorization", "").partition(" ")
            token = value.strip() if scheme.lower() == "bearer" else None
        if not _token_ok(config.api_token, token):
            await websocket.close(code=1008)  # policy violation
            return
        await websocket.accept()
        last_status = last_positions = None
        latest = await run_in_threadpool(model.logs, 1)
        last_log_id = latest[0]["id"] if latest else 0
        last_sent = time.time()
        try:
            while True:
                if time.time() - last_sent >= WS_PING_SEC:  # keeps proxies open, detects dead peers
                    await websocket.send_json({"type": "ping", "data": {"server_time": time.time()}})
                    last_sent = time.time()
                status, positions, new_logs = await run_in_threadpool(_snapshot, model, last_log_id)
                # server_time / heartbeat age change every second; compare without them
                status_key = {k: v for k, v in status.items() if k not in ("server_time", "heartbeat_age_sec")}
                if status_key != last_status:
                    last_status = status_key
                    await websocket.send_json({"type": "status", "data": {**status, "api_version": API_VERSION}})
                    last_sent = time.time()
                if positions != last_positions:
                    last_positions = positions
                    await websocket.send_json({"type": "positions", "data": positions})
                if new_logs:
                    last_log_id = new_logs[0]["id"]
                    await websocket.send_json({"type": "logs", "data": new_logs})
                await asyncio.sleep(WS_POLL_SEC)
        except (WebSocketDisconnect, RuntimeError):
            return

    return app


def _snapshot(model: BotReadModel, after_id: int):
    return model.status(), model.positions(), model.logs(200, after_id=after_id)
