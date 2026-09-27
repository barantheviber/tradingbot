"""
ccxt wrapper with retry/backoff.

All network calls to the exchange go through this module so retry policy,
logging and error classification live in exactly one place.

Errors are split into two buckets:

* Retryable  - transient issues where trying again is the right move:
  ccxt.NetworkError, ccxt.RequestTimeout, ccxt.RateLimitExceeded,
  ccxt.DDoSProtection, ccxt.ExchangeNotAvailable.
* Non-retryable - issues that will not resolve themselves by retrying:
  ccxt.AuthenticationError, ccxt.InsufficientFunds, ccxt.InvalidOrder,
  ccxt.PermissionDenied, and anything else not explicitly listed above.
  These are raised immediately so the caller can react (e.g. halt trading).
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, Optional, TypeVar

import ccxt

from config import Config, config as default_config

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_EXCEPTIONS = (
    ccxt.NetworkError,
    ccxt.RequestTimeout,
    ccxt.RateLimitExceeded,
    ccxt.DDoSProtection,
    ccxt.ExchangeNotAvailable,
)

NON_RETRYABLE_EXCEPTIONS = (
    ccxt.AuthenticationError,
    ccxt.InsufficientFunds,
    ccxt.InvalidOrder,
    ccxt.PermissionDenied,
    ccxt.BadSymbol,
)


class ExchangeClientError(Exception):
    """Raised when a non-retryable exchange error occurs."""


class RetryExhaustedError(Exception):
    """Raised when all retry attempts for a retryable error are exhausted."""


class ExchangeClient:
    """
    Thin, defensive wrapper around a ccxt exchange instance.

    Usage:
        client = ExchangeClient(config)
        candles = client.fetch_ohlcv("BTC/USDT", "15m", limit=300)
    """

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or default_config
        self._exchange = self._build_exchange()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_exchange(self) -> ccxt.Exchange:
        exchange_class = getattr(ccxt, self.cfg.exchange.exchange_id, None)
        if exchange_class is None:
            raise ExchangeClientError(
                f"Unknown exchange_id={self.cfg.exchange.exchange_id!r}"
            )
        params: dict[str, Any] = {
            "apiKey": self.cfg.exchange.api_key,
            "secret": self.cfg.exchange.api_secret,
            "enableRateLimit": True,
        }
        if self.cfg.exchange.api_password:
            params["password"] = self.cfg.exchange.api_password

        exchange = exchange_class(params)
        if self.cfg.exchange.sandbox:
            try:
                exchange.set_sandbox_mode(True)
            except Exception:  # pragma: no cover - not all exchanges support it
                logger.warning(
                    "Exchange %s does not support sandbox mode; continuing "
                    "with live endpoints. Make sure PAPER_TRADING covers you.",
                    self.cfg.exchange.exchange_id,
                )
        return exchange

    # ------------------------------------------------------------------
    # Retry machinery
    # ------------------------------------------------------------------
    def _call_with_retry(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        retry_cfg = self.cfg.retry
        attempt = 0
        while True:
            attempt += 1
            try:
                return func(*args, **kwargs)
            except NON_RETRYABLE_EXCEPTIONS as exc:
                logger.error(
                    "Non-retryable exchange error in %s: %s",
                    getattr(func, "__name__", func),
                    exc,
                )
                raise ExchangeClientError(str(exc)) from exc
            except RETRYABLE_EXCEPTIONS as exc:
                if attempt > retry_cfg.max_retries:
                    logger.error(
                        "Retry attempts exhausted (%d) for %s: %s",
                        retry_cfg.max_retries,
                        getattr(func, "__name__", func),
                        exc,
                    )
                    raise RetryExhaustedError(str(exc)) from exc
                delay = min(
                    retry_cfg.base_delay_seconds * (2 ** (attempt - 1)),
                    retry_cfg.max_delay_seconds,
                )
                delay += random.uniform(0, retry_cfg.jitter_seconds)
                logger.warning(
                    "Retryable exchange error (attempt %d/%d) in %s: %s. "
                    "Sleeping %.2fs before retrying.",
                    attempt,
                    retry_cfg.max_retries,
                    getattr(func, "__name__", func),
                    exc,
                    delay,
                )
                time.sleep(delay)
            except ccxt.BaseError as exc:
                # Anything else ccxt-specific we haven't explicitly classified:
                # treat conservatively as non-retryable so we don't loop
                # forever on something like a malformed request.
                logger.error(
                    "Unclassified ccxt error (treated as non-retryable) in "
                    "%s: %s",
                    getattr(func, "__name__", func),
                    exc,
                )
                raise ExchangeClientError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300, since: Optional[int] = None):
        return self._call_with_retry(
            self._exchange.fetch_ohlcv, symbol, timeframe=timeframe, limit=limit, since=since
        )

    def fetch_ticker(self, symbol: str):
        return self._call_with_retry(self._exchange.fetch_ticker, symbol)

    def fetch_balance(self):
        return self._call_with_retry(self._exchange.fetch_balance)

    def create_market_order(self, symbol: str, side: str, amount: float, params: Optional[dict] = None):
        return self._call_with_retry(
            self._exchange.create_order,
            symbol,
            "market",
            side,
            amount,
            None,
            params or {},
        )

    def create_limit_order(
        self, symbol: str, side: str, amount: float, price: float, params: Optional[dict] = None
    ):
        return self._call_with_retry(
            self._exchange.create_order,
            symbol,
            "limit",
            side,
            amount,
            price,
            params or {},
        )

    def cancel_order(self, order_id: str, symbol: str):
        return self._call_with_retry(self._exchange.cancel_order, order_id, symbol)

    def fetch_order(self, order_id: str, symbol: str):
        return self._call_with_retry(self._exchange.fetch_order, order_id, symbol)

    def load_markets(self):
        return self._call_with_retry(self._exchange.load_markets)

    @property
    def raw(self) -> ccxt.Exchange:
        """Escape hatch for advanced/rare calls not wrapped above."""
        return self._exchange
