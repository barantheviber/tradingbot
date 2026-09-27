import sqlite3
import tempfile
from pathlib import Path

import pytest

from state_manager import Position, StateManager, TradeRecord


@pytest.fixture
def state(tmp_path) -> StateManager:
    db_path = tmp_path / "test.sqlite3"
    sm = StateManager(db_path)
    yield sm
    sm.close()


class TestMigrations:
    def test_schema_version_recorded(self, state: StateManager):
        conn = sqlite3.connect(state.db_path)
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        conn.close()
        assert row is not None
        assert int(row[0]) == len(state._migrations)

    def test_migration_is_idempotent(self, tmp_path):
        db_path = tmp_path / "idempotent.sqlite3"
        sm1 = StateManager(db_path)
        sm1.set_setting("foo", "bar")
        sm1.close()

        # Re-opening should not error and should not wipe data.
        sm2 = StateManager(db_path)
        assert sm2.get_setting("foo") == "bar"
        sm2.close()

    def test_positions_table_has_meta_column(self, state: StateManager):
        conn = sqlite3.connect(state.db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(positions)")}
        conn.close()
        assert "meta" in cols


class TestSettings:
    def test_set_and_get_setting_roundtrip(self, state: StateManager):
        state.set_setting("risk_per_trade_pct", 1.5)
        assert state.get_setting("risk_per_trade_pct") == 1.5

    def test_get_setting_missing_key_returns_default(self, state: StateManager):
        assert state.get_setting("does_not_exist", "fallback") == "fallback"

    def test_seed_default_settings_does_not_overwrite_existing(self, state: StateManager):
        state.set_setting("risk_reward_ratio", 3.0)
        state.seed_default_settings({"risk_reward_ratio": 2.0, "atr_period": 14})
        assert state.get_setting("risk_reward_ratio") == 3.0
        assert state.get_setting("atr_period") == 14


class TestPositions:
    def test_open_and_close_position(self, state: StateManager):
        pos = Position(
            id=None,
            symbol="BTC/USDT",
            side="long",
            entry_price=100.0,
            quantity=1.0,
            stop_loss=90.0,
            take_profit=120.0,
            opened_at="2024-01-01T00:00:00+00:00",
        )
        pos_id = state.open_position(pos)
        open_positions = state.get_open_positions("BTC/USDT")
        assert len(open_positions) == 1
        assert open_positions[0].id == pos_id

        state.close_position(pos_id, close_price=110.0, realized_pnl=10.0)
        assert state.get_open_positions("BTC/USDT") == []
        closed = state.get_position(pos_id)
        assert closed.status == "closed"
        assert closed.realized_pnl == 10.0

    def test_update_position_stop(self, state: StateManager):
        pos = Position(
            id=None,
            symbol="ETH/USDT",
            side="long",
            entry_price=50.0,
            quantity=2.0,
            stop_loss=45.0,
            take_profit=60.0,
            opened_at="2024-01-01T00:00:00+00:00",
        )
        pos_id = state.open_position(pos)
        state.update_position_stop(pos_id, 48.0)
        updated = state.get_position(pos_id)
        assert updated.stop_loss == 48.0


class TestTrades:
    def test_record_and_fetch_trade_history(self, state: StateManager):
        trade = TradeRecord(
            id=None,
            symbol="BTC/USDT",
            side="long",
            entry_price=100.0,
            exit_price=110.0,
            quantity=1.0,
            pnl=10.0,
            opened_at="2024-01-01T00:00:00+00:00",
            closed_at="2024-01-01T01:00:00+00:00",
            reason="take_profit",
        )
        state.record_trade(trade)
        history = state.get_trade_history()
        assert len(history) == 1
        assert history[0].pnl == 10.0
