import json
import logging

from logging_setup import REDACTED, get_logger, setup_logging
from state_manager import StateManager

SECRET = "sk_live_SECRET_12345"


def _read(log_dir):
    with open(log_dir / "tradingbot.jsonl", encoding="utf-8") as fh:
        return fh.read()


def test_secret_redacted_in_message_extras_and_traceback(tmp_path, capsys):
    setup_logging(str(tmp_path), "INFO", secrets=[SECRET])
    log = get_logger("t")
    log.info(f"key {SECRET}", extra={"detail": f"bad key {SECRET}", "nested": {"k": SECRET}})
    try:
        raise RuntimeError(f"auth failed for {SECRET}")
    except RuntimeError:
        log.exception("boom")
    for handler in logging.getLogger("tradingbot").handlers:
        handler.flush()
    text = _read(tmp_path) + capsys.readouterr().out
    assert SECRET not in text
    assert REDACTED in text
    assert any("auth failed" in json.loads(line).get("exc", "") for line in _read(tmp_path).splitlines())


def test_secret_redacted_in_event_log(tmp_path):
    setup_logging(str(tmp_path), "INFO", secrets=[SECRET])
    state = StateManager(str(tmp_path / "t.db"))
    state.log_event("ERROR", "error", f"failed: {SECRET}", data={"detail": SECRET})
    event = state.get_events()[0]
    assert SECRET not in event["message"] and SECRET not in (event["data"] or "")
