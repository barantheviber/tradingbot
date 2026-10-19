"""Settings: built-in defaults, overridden by rewards_bot/config.json if present."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
DEFAULT_CONFIG_FILE = PACKAGE_DIR / "config.json"

BROWSERS = ("msedge", "chrome", "chromium")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    # "msedge" / "chrome" use the browser installed on the computer; "chromium"
    # needs `python -m playwright install chromium` once.
    browser: str = "msedge"
    executable_path: Optional[str] = None
    headless: bool = True
    language: str = "tr"
    country: str = "TR"

    desktop_searches: bool = True
    mobile_searches: bool = True
    daily_set: bool = True
    more_activities: bool = True

    # Random pause between two searches, seconds.
    search_delay_seconds: Tuple[float, float] = (12.0, 30.0)
    # Bing sometimes credits only a few searches per 15 minutes; when the
    # counter stops moving the bot waits this long before trying again.
    cooldown_minutes: float = 15.0
    # Consecutive batches without any new points before giving up for today.
    max_stalls: int = 3
    # Upper bound per platform and run, whatever the counters say.
    max_searches_per_run: int = 60
    # Used only when the points counters cannot be read.
    fallback_desktop_searches: int = 30
    fallback_mobile_searches: int = 20

    low_priority: bool = True

    # Windows Task Scheduler (install-task): daily start time plus a random delay.
    schedule_time: str = "10:00"
    schedule_random_delay_minutes: int = 90

    data_dir: Path = REPO_ROOT / "data" / "rewards"
    log_dir: Path = REPO_ROOT / "logs"

    @property
    def profile_dir(self) -> Path:
        return self.data_dir / "profile"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "run.lock"

    @property
    def locale(self) -> str:
        return f"{self.language}-{self.country}"


_FIELD_TYPES = {f.name: f.type for f in fields(Settings)}


def _coerce(name: str, value: Any) -> Any:
    kind = _FIELD_TYPES[name]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ConfigError(f"{name}: true/false olmalı, {value!r} verildi")
        return value
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{name}: sayı olmalı, {value!r} verildi")
        if value < 0:
            raise ConfigError(f"{name}: negatif olamaz")
        return int(value) if kind == "int" else float(value)
    if kind == "Tuple[float, float]":
        if (not isinstance(value, (list, tuple)) or len(value) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
            raise ConfigError(f"{name}: [en az, en çok] biçiminde iki sayı olmalı")
        lo, hi = float(value[0]), float(value[1])
        if lo < 0 or hi < lo:
            raise ConfigError(f"{name}: 0 <= en az <= en çok olmalı")
        return (lo, hi)
    if kind == "Path":
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{name}: klasör yolu olmalı")
        path = Path(value).expanduser()
        return path if path.is_absolute() else REPO_ROOT / path
    if kind == "Optional[str]":
        if value is not None and not isinstance(value, str):
            raise ConfigError(f"{name}: metin ya da null olmalı")
        return value or None
    if not isinstance(value, str):
        raise ConfigError(f"{name}: metin olmalı, {value!r} verildi")
    return value


def _validate(settings: Settings) -> Settings:
    if settings.browser not in BROWSERS:
        raise ConfigError(f"browser: {', '.join(BROWSERS)} değerlerinden biri olmalı")
    parts = settings.schedule_time.split(":")
    if (len(parts) != 2 or not all(p.isdigit() for p in parts)
            or not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59)):
        raise ConfigError("schedule_time: SS:DD biçiminde olmalı (ör. 10:00)")
    if settings.max_searches_per_run < 1:
        raise ConfigError("max_searches_per_run en az 1 olmalı")
    return settings


def settings_from_mapping(data: Mapping[str, Any], base: Settings = Settings()) -> Settings:
    unknown = sorted(set(data) - set(_FIELD_TYPES))
    if unknown:
        raise ConfigError(f"Bilinmeyen ayar(lar): {', '.join(unknown)}")
    return _validate(replace(base, **{k: _coerce(k, v) for k, v in data.items()}))


def load_settings(path: Optional[Path] = None) -> Settings:
    path = Path(path) if path else DEFAULT_CONFIG_FILE
    if not path.exists():
        return _validate(Settings())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path} okunamadı: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: en üstte bir JSON nesnesi olmalı")
    return settings_from_mapping(data)
