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

CLOCK_RESYNC_SEC = 3600
MAX_OHLCV_PAGES = 10

class AmbiguousOrderError(ccxt.NetworkError):
    """An order request failed in a way that does not tell whether the exchange
    accepted it (e.g. a timeout after sending), and a lookup by client order id
    could not settle it either. Never re-send such an order blindly."""

    def __init__(self, message: str, symbol: str, client_order_id: str, since_ms: int):
        super().__init__(message)
        self.symbol = symbol
        self.client_order_id = client_order_id
        self.since_ms = since_ms


class OrderNotPlaced(ccxt.ExchangeError):
    """A failed order request was confirmed absent on the exchange: safe to retry."""


ORDER_LOOKUP_ATTEMPTS = 3
ORDER_LOOKUP_DELAY_SEC = 2.0


def make_client_order_id(exchange_id: str, kind: str = "o") -> str:
    """A client order id every supported exchange accepts.

    Letters and digits only (OKX rejects '-'), short enough for Kraken's
    18-character free text, and 't-' prefixed for Gate (which requires it).
    """
    token = uuid.uuid4().hex
    if exchange_id.startswith("gate"):
        return f"t-tb{kind}{token[:20]}"
    if exchange_id.startswith("kraken"):
        return f"tb{kind}{token[:15]}"
    return f"tb{kind}{token[:24]}"


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
        self._clock_offset_ms = 0
        self._clock_synced_at: Optional[float] = None

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
        self.sync_clock()
        return markets

    def sync_clock(self) -> None:
        """Measure how far the local clock is from the exchange's (best effort).

        A local clock running ahead would make ``drop_unclosed_candles`` treat
        the still-forming candle as closed (look-ahead). Home PCs and phones
        drift, so candle closing uses exchange time when it is available.
        """
        self._clock_synced_at = time.monotonic()
        has = getattr(self.exchange, "has", None) or {}
        if not has.get("fetchTime"):
            return
        try:
            before = self._local_ms()
            server = self.call("fetch_time")
            after = self._local_ms()
        except Exception as exc:
            log.warning("Exchange time unavailable; using local clock", extra={"error": type(exc).__name__})
            return
        if server:
            self._clock_offset_ms = int(server) - (before + after) // 2
            if abs(self._clock_offset_ms) > 5_000:
                log.warning("Local clock differs from exchange time",
                            extra={"offset_sec": round(self._clock_offset_ms / 1000, 1)})

    def _ensure_markets(self) -> None:
        if not self._markets_loaded:
            self.load_markets()

    def _local_ms(self) -> int:
        try:
            return int(self.exchange.milliseconds())
        except Exception:
            return int(time.time() * 1000)

    def milliseconds(self) -> int:
        """Current time in exchange terms (local clock + measured offset)."""
        if self._clock_synced_at is not None and time.monotonic() - self._clock_synced_at > CLOCK_RESYNC_SEC:
            self.sync_clock()
        return self._local_ms() + self._clock_offset_ms

    def timeframe_ms(self, timeframe: str) -> int:
        return int(ccxt.Exchange.parse_timeframe(timeframe) * 1000)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500, since: Optional[int] = None) -> pd.DataFrame:
        rows = self.call("fetch_ohlcv", symbol, timeframe, since, limit)
        return ohlcv_to_frame(rows)

    def fetch_ohlcv_history(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """The latest ``limit`` candles, paging backwards when the exchange caps a
        single request (e.g. OKX 300, Binance 1000) below what the strategy needs."""
        df = self.fetch_ohlcv(symbol, timeframe, limit)
        tf_ms = self.timeframe_ms(timeframe)
        pages = 0
        while 0 < len(df) < limit and pages < MAX_OHLCV_PAGES:
            chunk = min(limit - len(df), len(df))
            oldest = int(df["timestamp"].iloc[0])
            older = self.fetch_ohlcv(symbol, timeframe, chunk, since=oldest - chunk * tf_ms)
            older = older[older["timestamp"] < oldest] if not older.empty else older
            if older.empty:
                break  # no more history on the exchange
            df = pd.concat([older, df]).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
            pages += 1
        return df.tail(limit).reset_index(drop=True)

    def fetch_closed_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        """OHLCV with the still-forming candle removed (no look-ahead)."""
        df = self.fetch_ohlcv_history(symbol, timeframe, limit)
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
        params.setdefault("clientOrderId", make_client_order_id(self.exchange_id, "o"))
        amount_p = float(self.exchange.amount_to_precision(symbol, amount))
        log.info("Placing market order", extra={"symbol": symbol, "side": side, "amount": amount_p,
                                                "client_order_id": params["clientOrderId"]})
        return self._place_order(symbol, params["clientOrderId"], "create_order", symbol, "market", side, amount_p,
                                 None, params)

    def _place_order(self, symbol: str, client_order_id: str, method: str, *args: Any) -> Dict[str, Any]:
        """Send an order. Rate-limit rejections are retried (the order was not
        taken); any other network error is settled by looking the order up by
        its client order id instead of re-sending it."""
        since = self.milliseconds()
        try:
            return self.call(method, *args, retry_on=ORDER_SAFE_RETRY_ERRORS)
        except ORDER_SAFE_RETRY_ERRORS:
            raise
        except ccxt.NetworkError as exc:
            log.error("Order outcome unknown; looking it up by client order id",
                      extra={"symbol": symbol, "client_order_id": client_order_id, "error": type(exc).__name__})
            return self.resolve_order(symbol, client_order_id, since, exc)

    def resolve_order(self, symbol: str, client_order_id: str, since_ms: int,
                      cause: Optional[Exception] = None) -> Dict[str, Any]:
        """Return the order the exchange has for ``client_order_id``; raise
        ``OrderNotPlaced`` if it is confirmed absent, or ``AmbiguousOrderError``
        if the exchange cannot be asked."""
        for attempt in range(ORDER_LOOKUP_ATTEMPTS):
            if attempt:
                self._sleep(ORDER_LOOKUP_DELAY_SEC)  # the exchange may list a new order with a delay
            try:
                order = self.find_order(symbol, client_order_id, since_ms)
            except ccxt.NotSupported:
                break
            except ccxt.NetworkError:
                continue
            if order is not None:
                log.warning("Order found on the exchange after an unclear response",
                            extra={"symbol": symbol, "client_order_id": client_order_id, "order_id": order.get("id")})
                return order
            if attempt == ORDER_LOOKUP_ATTEMPTS - 1:
                raise OrderNotPlaced(f"order {client_order_id} for {symbol} was not placed") from cause
        raise AmbiguousOrderError(f"order {client_order_id} for {symbol}: outcome unknown "
                                  f"({type(cause).__name__ if cause else 'lookup failed'})",
                                  symbol, client_order_id, since_ms)

    def find_order(self, symbol: str, client_order_id: str, since_ms: int) -> Optional[Dict[str, Any]]:
        """Search recent orders for ``client_order_id``. None = not there.
        Raises ``ccxt.NotSupported`` when the exchange offers no order listing."""
        has = getattr(self.exchange, "has", None) or {}
        searched = False
        for method, capability in (("fetch_open_orders", "fetchOpenOrders"),
                                   ("fetch_closed_orders", "fetchClosedOrders"),
                                   ("fetch_orders", "fetchOrders")):
            if not has.get(capability):
                continue
            searched = True
            for order in self.call(method, symbol, max(0, since_ms - 60_000)) or []:
                if order.get("clientOrderId") == client_order_id:
                    return order
        if not searched:
            raise ccxt.NotSupported(f"{self.exchange_id} cannot list orders")
        return None

    def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        return self.call("cancel_order", order_id, symbol)

    def supports_stop_orders(self) -> bool:
        has = getattr(self.exchange, "has", None) or {}
        return any(has.get(k) for k in ("createStopLossOrder", "createStopMarketOrder", "createStopOrder"))

    def create_stop_order(
        self, symbol: str, side: str, amount: float, stop_price: float, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Stop-market order that rests on the exchange and fires at ``stop_price``.

        Raises ``ccxt.NotSupported`` when the exchange offers no stop order type.
        Like market orders, it is only retried on errors that guarantee rejection.
        """
        self._ensure_markets()
        params = dict(params or {})
        params.setdefault("clientOrderId", make_client_order_id(self.exchange_id, "s"))
        amount_p = float(self.exchange.amount_to_precision(symbol, amount))
        price_p = float(self.exchange.price_to_precision(symbol, stop_price))
        has = getattr(self.exchange, "has", None) or {}
        log.info("Placing exchange stop order", extra={"symbol": symbol, "side": side, "amount": amount_p,
                                                       "stop_price": price_p,
                                                       "client_order_id": params["clientOrderId"]})
        if has.get("createStopLossOrder"):
            return self._place_order(symbol, params["clientOrderId"], "create_stop_loss_order", symbol, "market",
                                     side, amount_p, None, price_p, params)
        if has.get("createStopMarketOrder"):
            return self._place_order(symbol, params["clientOrderId"], "create_stop_market_order", symbol, side,
                                     amount_p, price_p, params)
        if has.get("createStopOrder"):
            return self._place_order(symbol, params["clientOrderId"], "create_stop_order", symbol, "market", side,
                                     amount_p, None, price_p, params)
        raise ccxt.NotSupported(f"{self.exchange_id} has no stop order type in ccxt")

    # ------------------------------------------------------------ precision
    def amount_to_precision(self, symbol: str, amount: float) -> float:
        self._ensure_markets()
        try:
            return float(self.exchange.amount_to_precision(symbol, amount))
        except ccxt.InvalidOrder:  # below minimum precision -> 0
            return 0.0

    def contract_size(self, symbol: str) -> float:
        """Base units per contract (1 for spot). ccxt order amounts on futures and
        swaps are in contracts, which differ from base units on e.g. OKX."""
        self._ensure_markets()
        market = self.exchange.market(symbol)
        if market.get("contract"):
            return float(market.get("contractSize") or 1.0)
        return 1.0

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
