"""Structured logging: JSON lines to a rotating file, readable lines to console.

Every record passes through ``SecretRedactingFilter`` so API keys can never
reach a log sink even if some library prints them by accident.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Iterable, List, Optional

LOGGER_NAME = "tradingbot"

# Attributes present on every LogRecord; anything else came from `extra=`.
_STD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message", "asctime"}


REDACTED = "***REDACTED***"

# Secrets registered by setup_logging; also used by StateManager.log_event so the
# event log the apps read is redacted the same way.
_REGISTERED_SECRETS: List[str] = []


def register_secrets(secrets: Iterable[str]) -> None:
    for secret in secrets:
        if secret and len(secret) >= 4 and secret not in _REGISTERED_SECRETS:
            _REGISTERED_SECRETS.append(secret)


def redact(text: str, secrets: Optional[Iterable[str]] = None) -> str:
    """Replace every registered (or given) secret in ``text``."""
    for secret in (_REGISTERED_SECRETS if secrets is None else secrets):
        if secret and secret in text:
            text = text.replace(secret, REDACTED)
    return text


class SecretRedactingFilter(logging.Filter):
    """Redacts the message, ``extra=`` fields, tracebacks and stack info."""

    def __init__(self, secrets: Iterable[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s and len(s) >= 4]

    def _redact_value(self, value):
        if isinstance(value, str):
            return redact(value, self._secrets)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        text = repr(value)
        return redact(text, self._secrets) if any(s in text for s in self._secrets) else value

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        msg = record.getMessage()
        redacted = redact(msg, self._secrets)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        for key, value in list(record.__dict__.items()):
            if key not in _STD_ATTRS and not key.startswith("_"):
                setattr(record, key, self._redact_value(value))
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text, self._secrets)
        if record.stack_info:
            record.stack_info = redact(record.stack_info, self._secrets)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_text or record.exc_info:
            payload["exc"] = record.exc_text or self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS and not k.startswith("_")
        }
        if extras:
            base += " | " + " ".join(f"{k}={v}" for k, v in extras.items())
        return base


def setup_logging(
    log_dir: str = "logs",
    level: str = "INFO",
    secrets: Optional[Iterable[str]] = None,
    extra_handlers: Optional[Iterable[logging.Handler]] = None,
) -> logging.Logger:
    """Configure the ``tradingbot`` logger tree. Safe to call more than once."""
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()

    secrets = list(secrets or [])
    register_secrets(secrets)
    redactor = SecretRedactingFilter(secrets)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ConsoleFormatter())
    console.addFilter(redactor)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "tradingbot.jsonl"), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(redactor)
    logger.addHandler(file_handler)

    for handler in extra_handlers or []:
        handler.addFilter(redactor)
        logger.addHandler(handler)

    # ccxt / urllib3 can be chatty; keep them at WARNING and redacted too.
    for noisy in ("ccxt", "urllib3"):
        lib_logger = logging.getLogger(noisy)
        lib_logger.setLevel(logging.WARNING)
        lib_logger.addFilter(redactor)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Child logger under the ``tradingbot`` tree, e.g. get_logger('engine')."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
