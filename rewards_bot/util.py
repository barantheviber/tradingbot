"""Small helpers: pacing, process priority, single-instance lock, run state, logging."""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import time
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Dict, Optional

LOGGER_NAME = "rewards_bot"
LOCK_STALE_SEC = 8 * 3600


class Pacer:
    """Random pauses; tests pass a no-op ``sleep``."""

    def __init__(self, rng: Optional[random.Random] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.rng = rng or random.Random()
        self._sleep = sleep

    def pause(self, low: float, high: float) -> None:
        self._sleep(self.rng.uniform(low, high))

    def wait_minutes(self, minutes: float) -> None:
        self._sleep(minutes * 60)


def lower_process_priority(log: logging.Logger) -> None:
    """Below-normal priority; the browser processes we start inherit it."""
    try:
        if sys.platform == "win32":
            import ctypes

            below_normal = 0x00004000
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), below_normal)
        else:
            os.nice(10)
    except Exception as exc:  # never worth failing a run over
        log.debug("Öncelik düşürülemedi: %s", exc)


class AlreadyRunning(RuntimeError):
    pass


class RunLock:
    """One run at a time (scheduled and manual runs share the browser profile)."""

    def __init__(self, path: Path, stale_after: float = LOCK_STALE_SEC):
        self.path = Path(path)
        self.stale_after = stale_after
        self._held = False

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age < self.stale_after:
                    raise AlreadyRunning(f"Bot zaten çalışıyor ({self.path} mevcut)")
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w") as handle:
                handle.write(str(os.getpid()))
            self._held = True
            return self
        raise AlreadyRunning(f"Kilit dosyası alınamadı: {self.path}")

    def __exit__(self, *exc) -> None:
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False


def read_state(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(path: Path, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def done_today(state: Dict[str, Any], today: date) -> bool:
    return state.get("last_success_date") == today.isoformat()


def setup_logging(log_dir: Path, verbose: bool = False) -> logging.Logger:
    log = logging.getLogger(LOGGER_NAME)
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.propagate = False
    for handler in list(log.handlers):
        log.removeHandler(handler)
        handler.close()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(Path(log_dir) / "rewards_bot.log", maxBytes=2_000_000,
                                       backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)
    # pythonw (scheduled runs) has no console: sys.stderr is None there.
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        log.addHandler(console)
    return log
