"""Bot + HTTP API in one process, for the installable apps.

The Windows app (through packaging/core_entry.py) and the Android app (through
Chaquopy, see mobile/plugins) both run the bot on the device itself and show
it through the API on 127.0.0.1. This module starts both in background
threads of one process and stops them together:

    runtime = LocalRuntime(".env")
    runtime.start()      # raises RuntimeStartError with a readable message
    ...
    runtime.stop()

The API is always bound to the loopback address here, whatever API_HOST says:
the apps talk to their own bot only, never over the network.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from config import DEFAULT_SETTINGS, ConfigError, legacy_env_warnings, load_config
from logging_setup import setup_logging
from state_manager import LegacyDatabaseError, StateManager

LOOPBACK = "127.0.0.1"
MIN_TOKEN_LENGTH = 16


class RuntimeStartError(Exception):
    """Configuration problem that keeps the bot from starting."""


class LocalRuntime:
    def __init__(self, env_file: str = ".env"):
        self.env_file = env_file
        self._engine = None
        self._server = None
        self._threads: list = []
        self._error: Optional[str] = None
        self._started_at: Optional[float] = None
        self.server_host = LOOPBACK
        self.log: Optional[logging.Logger] = None

    def start(self) -> None:
        if self.running:
            return
        self._error = None
        try:
            config = load_config(self.env_file)
        except ConfigError as exc:  # an unparsable value: the apps show it instead of retrying forever
            raise RuntimeStartError(str(exc)) from exc
        self.log = log = setup_logging(config.log_dir, config.log_level, secrets=config.secrets())
        for warning in legacy_env_warnings():
            log.warning(f"Config: {warning}")

        problems = list(config.validate())
        if len(config.api_token) < MIN_TOKEN_LENGTH:
            problems.append(f"API_TOKEN en az {MIN_TOKEN_LENGTH} karakter olmalı")
        if problems:
            for p in problems:
                log.error(f"Config error: {p}")
            raise RuntimeStartError("; ".join(problems))

        try:
            bot_state = StateManager(config.db_path)
            api_state = StateManager(config.db_path)
        except LegacyDatabaseError as exc:
            log.error(str(exc))
            raise RuntimeStartError(str(exc)) from exc
        bot_state.seed_default_settings(DEFAULT_SETTINGS)

        import uvicorn

        from api.server import create_app
        from main import build_engine

        for name in ("uvicorn", "uvicorn.error"):  # mask the token in ?token= URLs
            uv_logger = logging.getLogger(name)
            uv_logger.handlers = list(log.handlers)
            uv_logger.propagate = False
            uv_logger.setLevel(logging.INFO)

        log.info(f"Loaded {config}")
        if not config.paper_trading:
            log.warning("LIVE TRADING MODE - real orders will be sent to %s", config.exchange_id)

        self._engine = build_engine(config, bot_state)
        app = create_app(config, api_state)
        self._server = uvicorn.Server(uvicorn.Config(app, host=self.server_host, port=config.api_port,
                                                     access_log=False, log_config=None))
        self._threads = [
            threading.Thread(target=self._run_engine, name="bot-engine", daemon=True),
            threading.Thread(target=self._run_api, name="api-server", daemon=True),
        ]
        for t in self._threads:
            t.start()
        self._started_at = time.time()
        log.info(f"Local runtime started: API on http://{self.server_host}:{config.api_port} (mode={config.mode})")

    def _run_engine(self) -> None:
        try:
            self._engine.run()
        except Exception as exc:
            if self._engine.stopping and not self._error:
                return  # a stop requested during startup ends the exchange retry loop with its error
            self._error = f"Bot stopped: {type(exc).__name__}: {exc}"
            if self.log:
                self.log.critical(self._error)
        finally:
            # Without the bot the API only shows stale data: stop both together.
            if self._server is not None:
                self._server.should_exit = True

    def _run_api(self) -> None:
        try:
            self._server.run()
        except BaseException as exc:  # uvicorn exits with SystemExit when the port is taken
            self._error = f"API stopped: {type(exc).__name__}: {exc}"
            if self.log:
                self.log.critical(self._error)
        finally:
            if self._engine is not None:
                self._engine.request_stop("API stopped")

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def status(self) -> Dict[str, Any]:
        return {"running": self.running, "error": self._error, "started_at": self._started_at}

    def stop(self, timeout: float = 60.0) -> None:
        if self._engine is not None:
            self._engine.request_stop("app requested stop")
        if self._server is not None:
            self._server.should_exit = True
        deadline = time.monotonic() + timeout
        for t in self._threads:
            t.join(max(0.0, deadline - time.monotonic()))

    def wait(self, poll: float = 0.5) -> None:
        """Block until both threads end (used by the desktop core process)."""
        while self.running:
            time.sleep(poll)
