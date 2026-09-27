"""Central configuration.

Everything that is *environment* specific (exchange, keys, symbols, paths,
mode) is read from environment variables / `.env` here and nowhere else.

Everything that is *strategy / risk* specific lives in the SQLite settings
table (see ``state_manager.py``) so it can be changed live from the
dashboard. ``DEFAULT_SETTINGS`` below is only the seed used the first time a
key is missing from the database; the running bot always reads the value
from the database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:  # python-dotenv is optional at import time (tests do not need it)
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


LIVE_CONFIRM_PHRASE = "I_UNDERSTAND_THE_RISKS"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


class ConfigError(ValueError):
    """An environment variable has a value that cannot be parsed."""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        raise ConfigError(f"{name} bir tam sayı olmalı (şu an: {raw!r}).") from None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        raise ConfigError(f"{name} bir sayı olmalı (şu an: {raw!r}).") from None


def _env_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    return raw.strip() if raw not in (None, "") else default


# Env var names used by the short-lived earlier version of this bot (PR #2).
# They are NOT read any more; main.py warns when one is set so a .env copied
# from the old .env.example does not silently fall back to defaults.
LEGACY_ENV_VARS: Dict[str, str] = {
    "EXCHANGE_API_KEY": "API_KEY",
    "EXCHANGE_API_SECRET": "API_SECRET",
    "EXCHANGE_API_PASSWORD": "API_PASSWORD",
    "EXCHANGE_SANDBOX": "USE_TESTNET",
    "SYMBOL": "SYMBOLS",
    "CANDLE_LOOKBACK": "OHLCV_LIMIT",
    "POLL_INTERVAL_SECONDS": "POLL_INTERVAL_SEC",
    "RETRY_MAX_ATTEMPTS": "MAX_RETRIES",
    "DATA_DIR": "DB_PATH",
    "DB_FILENAME": "DB_PATH",
}
for _old in ("EMA_TREND_PERIOD", "RSI_PERIOD", "RSI_LOWER", "RSI_UPPER", "MACD_FAST", "MACD_SLOW", "MACD_SIGNAL",
             "VOLUME_MA_PERIOD", "VOLUME_CONFIRMATION_MULTIPLIER", "DONCHIAN_PERIOD", "ATR_PERIOD",
             "RISK_PER_TRADE_PCT", "RISK_REWARD_RATIO", "ATR_SL_MULTIPLIER", "TRAILING_ATR_MULTIPLIER",
             "MAX_DAILY_DRAWDOWN_PCT", "MAX_CONCURRENT_POSITIONS", "MAX_EXPOSURE_PER_SYMBOL_PCT"):
    LEGACY_ENV_VARS[_old] = "the live settings (dashboard or `python main.py --set`)"


def legacy_env_warnings() -> List[str]:
    """One message per legacy env var that is set (they are ignored)."""
    return [
        f"{old} is no longer read; use {new} instead (see .env.example)"
        for old, new in LEGACY_ENV_VARS.items()
        if os.getenv(old) not in (None, "")
    ]


# --------------------------------------------------------------------------
# Live-editable strategy / risk parameters (seed values only).
# Each entry: key -> (default value, description). The type of the default
# value is the type enforced when the setting is edited.
# --------------------------------------------------------------------------
DEFAULT_SETTINGS: Dict[str, tuple] = {
    # --- general switches
    "trading_enabled": (True, "Yeni pozisyon açılışına izin ver (kill switch)."),
    "allow_short": (False, "Short pozisyonlara izin ver (spot piyasada canlıda desteklenmez)."),
    # --- trend filter
    "ema_trend_period": (200, "Trend filtresi EMA periyodu."),
    # --- momentum
    "rsi_period": (14, "RSI periyodu."),
    "rsi_long_min": (45.0, "Long için RSI alt sınırı."),
    "rsi_long_max": (100.0, "Long için RSI üst sınırı (100 = sınır yok; gerçek veride güçlü trendleri kaçırmamak için)."),
    "rsi_short_min": (30.0, "Short için RSI alt sınırı (aşırı satım filtresi)."),
    "rsi_short_max": (55.0, "Short için RSI üst sınırı."),
    # --- MACD + volume
    "macd_fast": (12, "MACD hızlı EMA periyodu."),
    "macd_slow": (26, "MACD yavaş EMA periyodu."),
    "macd_signal": (9, "MACD sinyal periyodu."),
    "macd_cross_lookback": (3, "MACD kesişimi son kaç kapanmış mum içinde olmalı."),
    "volume_ma_period": (20, "Hacim ortalaması periyodu."),
    "volume_factor": (1.2, "Hacim, ortalamanın en az kaç katı olmalı."),
    # --- volatility breakout
    "atr_period": (14, "ATR periyodu."),
    "donchian_period": (20, "Donchian kanal periyodu."),
    "breakout_atr_buffer": (0.0, "Kırılımın kanalı en az kaç ATR aşması gerektiği."),
    # --- confirmation logic
    "min_confirmations": (3, "Trend filtresine ek olarak gereken teyit sayısı (momentum, MACD+hacim, kırılım: 1-3)."),
    "exit_on_trend_flip": (True, "Fiyat EMA trend çizgisinin ters tarafında kapanınca pozisyonu kapat."),
    # --- optional regime filters (0 = kapalı). Açıkken trend filtresi gibi zorunludur.
    "ema_slope_bars": (0, "Trend EMA'sı son N mumda yükseliyor (long) / düşüyor (short) olmalı. 0 = kapalı."),
    "adx_period": (14, "ADX periyodu (adx_min > 0 iken kullanılır)."),
    "adx_min": (0.0, "Giriş için en düşük ADX (trend gücü). 0 = kapalı."),
    "min_atr_pct": (0.0, "Giriş için ATR fiyatın en az yüzde kaçı olmalı (maliyetlere göre çok sakin piyasayı atlar). 0 = kapalı."),
    # --- risk
    "risk_per_trade_pct": (1.0, "İşlem başına riske edilen özsermaye yüzdesi."),
    "atr_sl_multiplier": (3.0, "Stop-loss mesafesi = ATR x bu katsayı. Pozisyon boyutu buna göre küçülür, işlem başı risk değişmez."),
    "risk_reward_ratio": (10.0, "Take-profit mesafesi = stop mesafesi x bu oran (10 = kazançlar çoğunlukla trailing stop ile kapanır)."),
    "trailing_enabled": (True, "Trailing stop aktif."),
    "trailing_atr_multiplier": (5.0, "Trailing stop mesafesi = ATR x bu katsayı."),
    "trailing_activation_r": (1.0, "Trailing stop, fiyat kaç R lehimize gidince devreye girsin (0 = hemen)."),
    "daily_loss_limit_pct": (5.0, "Günlük zarar bu yüzdeyi aşarsa UTC gece yarısına kadar yeni pozisyon açma."),
    "max_open_positions": (3, "Maksimum eşzamanlı açık pozisyon."),
    "max_symbol_exposure_pct": (25.0, "Sembol başına maksimum pozisyon büyüklüğü (özsermaye yüzdesi)."),
}


def default_settings_values() -> Dict[str, Any]:
    return {k: v[0] for k, v in DEFAULT_SETTINGS.items()}


@dataclass
class Config:
    # exchange
    exchange_id: str = "binance"
    market_type: str = "spot"  # spot | future | swap
    use_testnet: bool = False
    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)
    api_password: str = field(default="", repr=False)

    # mode
    paper_trading: bool = True
    live_confirm: str = field(default="", repr=False)

    # market
    symbols: List[str] = field(default_factory=lambda: ["BTC/USDT"])
    timeframe: str = "4h"
    ohlcv_limit: int = 500

    # engine
    poll_interval_sec: int = 30
    db_path: str = "data/tradingbot.db"
    log_dir: str = "logs"
    log_level: str = "INFO"

    # paper account
    paper_starting_balance: float = 10_000.0
    paper_fee_rate: float = 0.001  # 0.1 %
    paper_slippage_bps: float = 5.0  # 0.05 %

    # retry
    max_retries: int = 5
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0

    # HTTP API for the mobile / desktop apps (api/)
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_token: str = field(default="", repr=False)
    api_cors_origins: List[str] = field(default_factory=list)

    @property
    def quote_currency(self) -> str:
        return self.symbols[0].split("/")[1].split(":")[0] if self.symbols else "USDT"

    @property
    def mode(self) -> str:
        return "paper" if self.paper_trading else "live"

    def secrets(self) -> List[str]:
        """Values that must never appear in logs."""
        return [s for s in (self.api_key, self.api_secret, self.api_password, self.api_token) if s]

    def validate(self) -> List[str]:
        """Return a list of problems. Empty list means the config is usable."""
        problems: List[str] = []
        if not self.symbols:
            problems.append("SYMBOLS boş olamaz.")
        if self.poll_interval_sec < 1:
            problems.append("POLL_INTERVAL_SEC en az 1 olmalı.")
        if self.market_type not in {"spot", "future", "swap", "margin"}:
            problems.append(f"MARKET_TYPE geçersiz: {self.market_type}")
        if not _valid_timeframe(self.timeframe):
            problems.append(f"TIMEFRAME geçersiz: {self.timeframe!r} (ör. 15m, 1h, 4h, 1d)")
        if self.ohlcv_limit < 1:
            problems.append("OHLCV_LIMIT en az 1 olmalı.")
        if self.paper_starting_balance <= 0:
            problems.append("PAPER_STARTING_BALANCE sıfırdan büyük olmalı.")
        if not 0 <= self.paper_fee_rate < 0.1:
            problems.append("PAPER_FEE_RATE 0 ile 0.1 arasında olmalı (0.001 = %0.1).")
        if self.paper_slippage_bps < 0:
            problems.append("PAPER_SLIPPAGE_BPS negatif olamaz.")
        if self.max_retries < 0:
            problems.append("MAX_RETRIES negatif olamaz.")
        if self.retry_base_delay <= 0 or self.retry_max_delay < self.retry_base_delay:
            problems.append("RETRY_BASE_DELAY > 0 ve RETRY_MAX_DELAY >= RETRY_BASE_DELAY olmalı.")
        if any("/" not in s for s in self.symbols):
            problems.append("SYMBOLS 'BASE/QUOTE' biçiminde olmalı (ör. BTC/USDT).")
        if not self.paper_trading:
            if not (self.api_key and self.api_secret):
                problems.append("Canlı mod için API_KEY ve API_SECRET .env içinde tanımlı olmalı.")
            if self.live_confirm != LIVE_CONFIRM_PHRASE:
                problems.append(
                    "Canlı mod bilinçli bir adım gerektirir: .env içinde "
                    f"LIVE_TRADING_CONFIRM={LIVE_CONFIRM_PHRASE} ayarlayın."
                )
        return problems

    def __repr__(self) -> str:  # never print secrets
        return (
            f"Config(exchange_id={self.exchange_id!r}, market_type={self.market_type!r}, "
            f"testnet={self.use_testnet}, mode={self.mode!r}, symbols={self.symbols}, "
            f"timeframe={self.timeframe!r}, db_path={self.db_path!r}, "
            f"api_key={'***' if self.api_key else 'unset'})"
        )

    __str__ = __repr__


def _valid_timeframe(timeframe: str) -> bool:
    try:
        import ccxt

        return ccxt.Exchange.parse_timeframe(timeframe) > 0
    except Exception:
        return False


def load_config(env_file: Optional[str] = ".env") -> Config:
    """Build a Config from environment variables (optionally loading .env)."""
    if load_dotenv is not None and env_file and os.path.exists(env_file):
        load_dotenv(env_file, override=False)

    symbols = [s.strip() for s in _env_str("SYMBOLS", "BTC/USDT").split(",") if s.strip()]
    return Config(
        exchange_id=_env_str("EXCHANGE_ID", "binance").lower(),
        market_type=_env_str("MARKET_TYPE", "spot").lower(),
        use_testnet=_env_bool("USE_TESTNET", False),
        api_key=_env_str("API_KEY"),
        api_secret=_env_str("API_SECRET"),
        api_password=_env_str("API_PASSWORD"),
        paper_trading=_env_bool("PAPER_TRADING", True),
        live_confirm=_env_str("LIVE_TRADING_CONFIRM"),
        symbols=symbols,
        timeframe=_env_str("TIMEFRAME", "4h"),
        ohlcv_limit=_env_int("OHLCV_LIMIT", 500),
        poll_interval_sec=_env_int("POLL_INTERVAL_SEC", 30),
        db_path=_env_str("DB_PATH", "data/tradingbot.db"),
        log_dir=_env_str("LOG_DIR", "logs"),
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        paper_starting_balance=_env_float("PAPER_STARTING_BALANCE", 10_000.0),
        paper_fee_rate=_env_float("PAPER_FEE_RATE", 0.001),
        paper_slippage_bps=_env_float("PAPER_SLIPPAGE_BPS", 5.0),
        max_retries=_env_int("MAX_RETRIES", 5),
        retry_base_delay=_env_float("RETRY_BASE_DELAY", 1.0),
        retry_max_delay=_env_float("RETRY_MAX_DELAY", 30.0),
        api_host=_env_str("API_HOST", "127.0.0.1"),
        api_port=_env_int("API_PORT", 8000),
        api_token=_env_str("API_TOKEN"),
        api_cors_origins=[o.strip() for o in _env_str("API_CORS_ORIGINS").split(",") if o.strip()],
    )
