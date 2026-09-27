"""Thin ccxt wrapper with retry, exponential backoff and jitter.

Error policy
------------
* Retryable: ``NetworkError`` and its subclasses (``RequestTimeout``,
  ``ExchangeNotAvailable``, ``RateLimitExceeded``, ``DDoSProtection``...).
* Never retried (fail fast): ``AuthenticationError``, ``PermissionDenied``,
  ``InsufficientFunds``, ``InvalidOrder``, ``BadSymbol`` and any other
  ``ExchangeError`` - retrying them cannot succeed and may hide a real bug.

Order placement is special: a timeout after the request left our machine
may still have created the order on the exchange, so ``create_market_order``
only retries errors that guarantee the order was rejected up front
(``RateLimitExceeded`` / ``DDoSProtection``). Other network errors are
raised so the engine can reconcile on the next loop instead of risking a
duplicate order.
"""

from __future__ import annotations

import random
import time
import uuid
from typing import Any, Callable, Dict, Optional, Tuple, Type

import ccxt
import pandas as pd

from logging_setup import get_logger

log = get_logger("exchange")

RETRYABLE_ERRORS: Tuple[Type[Exception], ...] = (
    ccxt.RateLimitExceeded,
    ccxt.DDoSProtection,
    ccxt.RequestTimeout,
    ccxt.ExchangeNotAvailable,
    ccxt.NetworkError,
)
NON_RETRYABLE_ERRORS: Tuple[Type[Exception], ...] = (
    ccxt.AuthenticationError,
    ccxt.PermissionDenied,
    ccxt.AccountSuspended,
    ccxt.InsufficientFunds,
    ccxt.InvalidOrder,
    ccxt.BadSymbol,
    ccxt.BadRequest,
)
ORDER_SAFE_RETRY_ERRORS: Tuple[Type[Exception], ...] = (ccxt.RateLimitExceeded, ccxt.DDoSProtection)

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def backoff_delay(attempt: int, base: float, cap: float, rng: Callable[[float, float], float] = random.uniform) -> float:
    """Exponential backoff with jitter: uniform(base/2, min(cap, base * 2**attempt))."""
    ceiling = min(cap, base * (2 ** attempt))
    return rng(min(base / 2, ceiling), ceiling)


class ExchangeClient:
    def __init__(
        self,
        exchange_id: str,
        api_key: str = "",
        api_secret: str = "",
        api_password: str = "",
        market_type: str = "spot",
        use_testnet: bool = False,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exchange: Optional[Any] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.exchange_id = exchange_id
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep_fn
        self._markets_loaded = False

        if exchange is not None:  # injected (tests)
            self.exchange = exchange
            return

        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"Unknown EXCHANGE_ID for ccxt: {exchange_id!r}")
        params: Dict[str, Any] = {"enableRateLimit": True, "options": {"defaultType": market_type}}
        if api_key and api_secret:
            params["apiKey"] = api_key
            params["secret"] = api_secret
        if api_password:
            params["password"] = api_password
        self.exchange = getattr(ccxt, exchange_id)(params)
        if use_testnet:
            self.exchange.set_sandbox_mode(True)
        log.info(
            "Exchange client ready",
            extra={"exchange": exchange_id, "market_type": market_type, "testnet": use_testnet,
                   "authenticated": bool(api_key and api_secret)},
        )

    @classmethod
    def from_config(cls, config, public_only: bool = False) -> "ExchangeClient":
        """Build from Config. ``public_only`` never passes API keys (paper mode, dashboard)."""
        use_keys = not public_only
        return cls(
            exchange_id=config.exchange_id,
            api_key=config.api_key if use_keys else "",
            api_secret=config.api_secret if use_keys else "",
            api_password=config.api_password if use_keys else "",
            market_type=config.market_type,
            use_testnet=config.use_testnet,
            max_retries=config.max_retries,
            base_delay=config.retry_base_delay,
            max_delay=config.retry_max_delay,
        )

    # ------------------------------------------------------------------ retry
    def call(
        self,
        method: str,
        *args: Any,
        retry_on: Tuple[Type[Exception], ...] = RETRYABLE_ERRORS,
        **kwargs: Any,
    ) -> Any:
        """Call ``self.exchange.<method>`` with retry/backoff on ``retry_on`` errors."""
        fn = getattr(self.exchange, method)
        attempt = 0
        while True:
            try:
                return fn(*args, **kwargs)
            except NON_RETRYABLE_ERRORS as exc:
                log.error("Non-retryable exchange error", extra={"method": method, "error": type(exc).__name__,
                                                                  "detail": str(exc)[:300]})
                raise
            except retry_on as exc:
                if attempt >= self.max_retries:
                    log.error("Exchange call failed after retries",
                              extra={"method": method, "attempts": attempt + 1, "error": type(exc).__name__})
                    raise
                delay = backoff_delay(attempt, self.base_delay, self.max_delay)
                if isinstance(exc, (ccxt.RateLimitExceeded, ccxt.DDoSProtection)):
                    delay = min(self.max_delay, delay * 2)
                log.warning("Retryable exchange error, backing off",
                            extra={"method": method, "attempt": attempt + 1, "error": type(exc).__name__,
                                   "delay_sec": round(delay, 2)})
                self._sleep(delay)
                attempt += 1

    # --------------------------------------------------------------- market
    def load_markets(self, reload: bool = False) -> Dict[str, Any]:
        markets = self.call("load_markets", reload)
        self._markets_loaded = True
        return markets

    def _ensure_markets(self) -> None:
        if not self._markets_loaded:
            self.load_markets()

    def milliseconds(self) -> int:
        try:
            return int(self.exchange.milliseconds())
        except Exception:  # pragma: no cover
            return int(time.time() * 1000)

    def timeframe_ms(self, timeframe: str) -> int:
        return int(ccxt.Exchange.parse_timeframe(timeframe) * 1000)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500, since: Optional[int] = None) -> pd.DataFrame:
        rows = self.call("fetch_ohlcv", symbol, timeframe, since, limit)
        return ohlcv_to_frame(rows)

    def fetch_closed_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        """OHLCV with the still-forming candle removed (no look-ahead)."""
        df = self.fetch_ohlcv(symbol, timeframe, limit)
        return drop_unclosed_candles(df, self.timeframe_ms(timeframe), self.milliseconds())

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return self.call("fetch_ticker", symbol)

    def fetch_last_price(self, symbol: str) -> float:
        ticker = self.fetch_ticker(symbol)
        price = ticker.get("last") or ticker.get("close")
        if price is None and ticker.get("bid") and ticker.get("ask"):
            price = (ticker["bid"] + ticker["ask"]) / 2
        if price is None:
            raise ccxt.ExchangeError(f"No price in ticker for {symbol}")
        return float(price)

    # -------------------------------------------------------------- account
    def fetch_balance(self) -> Dict[str, Any]:
        return self.call("fetch_balance")

    def fetch_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        return self.call("fetch_order", order_id, symbol)

    def create_market_order(
        self, symbol: str, side: str, amount: float, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        self._ensure_markets()
        params = dict(params or {})
        params.setdefault("clientOrderId", f"tb-{uuid.uuid4().hex[:20]}")
        amount_p = float(self.exchange.amount_to_precision(symbol, amount))
        log.info("Placing market order", extra={"symbol": symbol, "side": side, "amount": amount_p,
                                                "client_order_id": params["clientOrderId"]})
        return self.call("create_order", symbol, "market", side, amount_p, None, params,
                         retry_on=ORDER_SAFE_RETRY_ERRORS)

    # ------------------------------------------------------------ precision
    def amount_to_precision(self, symbol: str, amount: float) -> float:
        self._ensure_markets()
        try:
            return float(self.exchange.amount_to_precision(symbol, amount))
        except ccxt.InvalidOrder:  # below minimum precision -> 0
            return 0.0

    def market_limits(self, symbol: str) -> Dict[str, Optional[float]]:
        self._ensure_markets()
        market = self.exchange.market(symbol)
        limits = market.get("limits") or {}
        return {
            "min_amount": (limits.get("amount") or {}).get("min"),
            "min_cost": (limits.get("cost") or {}).get("min"),
        }


def ohlcv_to_frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows or [], columns=OHLCV_COLUMNS)
    if df.empty:
        return df
    df = df.astype({"timestamp": "int64", "open": float, "high": float, "low": float, "close": float,
                    "volume": float})
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return df


def drop_unclosed_candles(df: pd.DataFrame, timeframe_ms: int, now_ms: int) -> pd.DataFrame:
    """Keep only candles whose close time (open + timeframe) is in the past."""
    if df.empty:
        return df
    return df[df["timestamp"] + timeframe_ms <= now_ms].reset_index(drop=True)
