import json

import pytest

from config import DEFAULT_SETTINGS
import sqlite3

from state_manager import MIGRATIONS, LegacyDatabaseError, StateManager


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "state.db")


def test_migrations_run_once_and_are_idempotent(db):
    s1 = StateManager(db)
    assert s1.schema_version() == MIGRATIONS[-1][0]
    s1.close()
    s2 = StateManager(db)  # re-open: no error, same version, single row per version
    rows = s2._query("SELECT version FROM schema_version")
    assert [r["version"] for r in rows] == [v for v, _ in MIGRATIONS]


def test_seed_keeps_user_edits(db):
    s = StateManager(db)
    s.seed_default_settings(DEFAULT_SETTINGS)
    s.set_setting("risk_per_trade_pct", "0.5")
    s.seed_default_settings(DEFAULT_SETTINGS)
    assert s.get_setting("risk_per_trade_pct") == 0.5
    assert s.get_all_settings()["ema_trend_period"] == 200


def test_set_setting_type_coercion(db):
    s = StateManager(db)
    s.seed_default_settings(DEFAULT_SETTINGS)
    assert s.set_setting("max_open_positions", "4") == 4
    assert s.set_setting("trailing_enabled", "false") is False
    assert s.set_setting("volume_factor", 2) == 2.0 and isinstance(s.get_setting("volume_factor"), float)
    with pytest.raises(ValueError):
        s.set_setting("max_open_positions", "2.5")
    with pytest.raises(ValueError):
        s.set_setting("trailing_enabled", "maybe")


def test_positions_survive_restart(db):
    s = StateManager(db)
    pid = s.open_position(symbol="BTC/USDT", side="long", quantity=0.1, entry_price=100, stop_loss=95,
                          take_profit=110, atr_at_entry=2.5, mode="paper")
    s.close()
    restored = StateManager(db).get_open_positions(mode="paper")
    assert len(restored) == 1
    p = restored[0]
    assert p["id"] == pid and p["initial_stop"] == 95 and p["highest_price"] == 100
    assert StateManager(db).get_open_positions(mode="live") == []


def test_close_position_and_realized_pnl(db):
    s = StateManager(db)
    pid = s.open_position(symbol="X/USDT", side="long", quantity=1, entry_price=100, stop_loss=95,
                          take_profit=110, mode="paper", fees=0.1)
    assert s.open_fees("paper") == pytest.approx(0.1)
    s.mark_position_closed(pid, exit_price=110, pnl=9.8, fees=0.2, reason="take_profit")
    assert s.get_open_positions() == []
    assert s.realized_pnl("paper") == pytest.approx(9.8)
    assert s.get_closed_positions()[0]["exit_reason"] == "take_profit"


def test_day_start_equity_is_fixed_per_utc_day(db):
    s = StateManager(db)
    assert s.get_or_create_day_start_equity("paper", 1000, date="2026-01-01") == 1000
    assert s.get_or_create_day_start_equity("paper", 900, date="2026-01-01") == 1000
    assert s.get_or_create_day_start_equity("paper", 900, date="2026-01-02") == 900  # new UTC day resets


def test_commands_and_runtime_state(db):
    s = StateManager(db)
    cid = s.enqueue_command("close_position", {"position_id": 3})
    pending = s.get_pending_commands()
    assert pending[0]["id"] == cid and pending[0]["payload"] == {"position_id": 3}
    s.complete_command(cid, "done", "ok")
    assert s.get_pending_commands() == []
    s.set_state("last_candle:BTC/USDT:1h", 123)
    assert s.get_state("last_candle:BTC/USDT:1h") == 123
    assert s.get_state("missing", "d") == "d"


def test_refuses_database_from_earlier_version(db):
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', '2')")
    conn.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, symbol TEXT, close_price REAL)")
    conn.commit()
    conn.close()
    with pytest.raises(LegacyDatabaseError):
        StateManager(db)
    # the old file is left untouched
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "schema_version" not in tables and "settings" not in tables


def test_migration_2_moves_untouched_old_defaults_only(tmp_path):
    import sqlite3

    from config import DEFAULT_SETTINGS
    from state_manager import MIGRATIONS, RETUNED_DEFAULTS_2, StateManager

    PREVIOUS_DEFAULTS_V1 = {k: old for k, (old, _) in RETUNED_DEFAULTS_2.items()}
    assert all(DEFAULT_SETTINGS[k][0] == new for k, (_, new) in RETUNED_DEFAULTS_2.items())

    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    dict(MIGRATIONS)[1](conn)
    conn.execute("INSERT INTO schema_version(version) VALUES (1)")
    for key, value in {**PREVIOUS_DEFAULTS_V1, "risk_reward_ratio": 3.0}.items():  # user edited R:R
        conn.execute("INSERT INTO settings(key, value, description, updated_at) VALUES (?, ?, '', 'x')",
                     (key, json.dumps(value)))
    conn.close()

    sm = StateManager(path)
    assert sm.schema_version() >= 2
    assert sm.get_setting("atr_sl_multiplier") == DEFAULT_SETTINGS["atr_sl_multiplier"][0]
    assert sm.get_setting("trailing_atr_multiplier") == DEFAULT_SETTINGS["trailing_atr_multiplier"][0]
    assert sm.get_setting("rsi_long_max") == DEFAULT_SETTINGS["rsi_long_max"][0]
    assert sm.get_setting("risk_reward_ratio") == 3.0  # kept


def test_new_database_gets_new_defaults(tmp_path):
    from config import DEFAULT_SETTINGS
    from state_manager import StateManager

    sm = StateManager(str(tmp_path / "new.db"))
    sm.seed_default_settings(DEFAULT_SETTINGS)
    assert sm.get_setting("atr_sl_multiplier") == DEFAULT_SETTINGS["atr_sl_multiplier"][0]
