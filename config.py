"""
Central configuration for the trading bot.

Every tunable value that isn't meant to change *live* (see state_manager.py
for the live-editable strategy/risk parameters) is defined here and can be
overridden via environment variables (typically loaded from a .env file).

Nothing in this module ever logs or prints the API secret/key values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    # Optional dependency: if python-dotenv isn't installed, we simply rely
    # on the environment already being populated (e.g. by the shell, or by
    # a process manager / systemd unit / docker-compose env_file).
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - exercised only when dotenv missing
    pass


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return float(val)


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return int(val)


@dataclass(frozen=True)
class ExchangeConfig:
    exchange_id: str = os.getenv("EXCHANGE_ID", "binance")
    api_key: str = os.getenv("EXCHANGE_API_KEY", "")
    api_secret: str = os.getenv("EXCHANGE_API_SECRET", "")
    # Some exchanges (e.g. some ccxt integrations for KuCoin, OKX) need a
    # third credential, commonly called a "password" or "passphrase".
    api_password: str = os.getenv("EXCHANGE_API_PASSWORD", "")
    sandbox: bool = _env_bool("EXCHANGE_SANDBOX", True)

    def __repr__(self) -> str:  # never leak secrets in logs/repr
        return (
            f"ExchangeConfig(exchange_id={self.exchange_id!r}, "
            f"sandbox={self.sandbox!r}, api_key=***, api_secret=***, "
            f"api_password=***)"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = _env_int("RETRY_MAX_ATTEMPTS", 5)
    base_delay_seconds: float = _env_float("RETRY_BASE_DELAY", 1.0)
    max_delay_seconds: float = _env_float("RETRY_MAX_DELAY", 30.0)
    jitter_seconds: float = _env_float("RETRY_JITTER", 0.5)


@dataclass(frozen=True)
class TradingConfig:
    symbol: str = os.getenv("SYMBOL", "BTC/USDT")
    timeframe: str = os.getenv("TIMEFRAME", "15m")
    # How many closed candles of history to keep/fetch for indicator warmup.
    candle_lookback: int = _env_int("CANDLE_LOOKBACK", 300)
    # How often (seconds) the main loop checks whether a new candle closed.
    poll_interval_seconds: int = _env_int("POLL_INTERVAL_SECONDS", 5)


@dataclass(frozen=True)
class RiskDefaults:
    """
    Defaults used only to *seed* the state_manager settings table the first
    time the database is created. After that, these values live in SQLite
    and are editable live from the dashboard - changing them here has no
    effect on an existing database.
    """
    risk_per_trade_pct: float = _env_float("RISK_PER_TRADE_PCT", 1.0)
    risk_reward_ratio: float = _env_float("RISK_REWARD_RATIO", 2.0)
    atr_period: int = _env_int("ATR_PERIOD", 14)
    atr_sl_multiplier: float = _env_float("ATR_SL_MULTIPLIER", 1.5)
    trailing_atr_multiplier: float = _env_float("TRAILING_ATR_MULTIPLIER", 1.5)
    max_daily_drawdown_pct: float = _env_float("MAX_DAILY_DRAWDOWN_PCT", 5.0)
    max_concurrent_positions: int = _env_int("MAX_CONCURRENT_POSITIONS", 3)
    max_exposure_per_symbol_pct: float = _env_float(
        "MAX_EXPOSURE_PER_SYMBOL_PCT", 20.0
    )
    ema_trend_period: int = _env_int("EMA_TREND_PERIOD", 200)
    rsi_period: int = _env_int("RSI_PERIOD", 14)
    rsi_lower: float = _env_float("RSI_LOWER", 40.0)
    rsi_upper: float = _env_float("RSI_UPPER", 70.0)
    macd_fast: int = _env_int("MACD_FAST", 12)
    macd_slow: int = _env_int("MACD_SLOW", 26)
    macd_signal: int = _env_int("MACD_SIGNAL", 9)
    volume_ma_period: int = _env_int("VOLUME_MA_PERIOD", 20)
    volume_confirmation_multiplier: float = _env_float(
        "VOLUME_CONFIRMATION_MULTIPLIER", 1.2
    )
    donchian_period: int = _env_int("DONCHIAN_PERIOD", 20)


@dataclass(frozen=True)
class AccountConfig:
    # Starting paper balance, in quote currency (e.g. USDT).
    paper_starting_balance: float = _env_float("PAPER_STARTING_BALANCE", 10_000.0)
    quote_currency: str = os.getenv("QUOTE_CURRENCY", "USDT")


@dataclass(frozen=True)
class PathsConfig:
    base_dir: Path = Path(os.getenv("BOT_BASE_DIR", str(Path(__file__).resolve().parent)))
    data_dir: Path = field(init=False)
    db_path: Path = field(init=False)
    log_dir: Path = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "data_dir", self.base_dir / "data")
        object.__setattr__(self, "db_path", self.data_dir / os.getenv("DB_FILENAME", "trading_bot.sqlite3"))
        object.__setattr__(self, "log_dir", self.base_dir / "logs")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Config:
    paper_trading: bool = _env_bool("PAPER_TRADING", True)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk_defaults: RiskDefaults = field(default_factory=RiskDefaults)
    account: AccountConfig = field(default_factory=AccountConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)

    def validate(self) -> None:
        """Fail fast on obviously-broken configuration."""
        if not self.paper_trading:
            if not self.exchange.api_key or not self.exchange.api_secret:
                raise ValueError(
                    "PAPER_TRADING=False requires EXCHANGE_API_KEY and "
                    "EXCHANGE_API_SECRET to be set."
                )
        if self.risk_defaults.risk_per_trade_pct <= 0:
            raise ValueError("RISK_PER_TRADE_PCT must be > 0")
        if self.risk_defaults.max_daily_drawdown_pct <= 0:
            raise ValueError("MAX_DAILY_DRAWDOWN_PCT must be > 0")
        if self.risk_defaults.max_concurrent_positions <= 0:
            raise ValueError("MAX_CONCURRENT_POSITIONS must be > 0")


config = Config()
