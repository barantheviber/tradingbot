"""Live execution against a mocked exchange: partial exit fills and
exchange-side protective stop orders."""

import ccxt
import pytest

from bot_engine import BotEngine
from config import DEFAULT_SETTINGS, Config
from execution import LiveExecutionClient
from risk_manager import RiskManager
from state_manager import StateManager


@pytest.fixture
def state(tmp_path):
    s = StateManager(str(tmp_path / "t.db"))
    s.seed_default_settings(DEFAULT_SETTINGS)
    return s


class FakeExchange:
    """Stands in for ExchangeClient. ``fills`` queues the filled amount of the
    next market orders (None = fill everything)."""

    def __init__(self, stops_supported=True, min_amount=None):
        self.calls = []
        self.fills = []
        self.stops = {}  # id -> order dict
        self.stops_supported = stops_supported
        self.min_amount = min_amount
        self.price = 100.0
        self._next = 0

    def _id(self):
        self._next += 1
        return str(self._next)

    def create_market_order(self, symbol, side, amount, params=None):
        filled = self.fills.pop(0) if self.fills else amount
        oid = self._id()
        self.calls.append(("market", side, amount, dict(params or {})))
        return {"id": oid, "average": self.price, "filled": filled, "status": "closed" if filled == amount else
                "canceled", "fee": {"cost": 0.0, "currency": "USDT"}}

    def fetch_order(self, order_id, symbol):
        self.calls.append(("fetch", order_id))
        if order_id not in self.stops:
            raise ccxt.OrderNotFound(order_id)
        return dict(self.stops[order_id])

    def cancel_order(self, order_id, symbol):
        self.calls.append(("cancel", order_id))
        order = self.stops.get(order_id)
        if order is None or order["status"] != "open":
            raise ccxt.OrderNotFound(order_id)
        order["status"] = "canceled"
        return order

    def supports_stop_orders(self):
        return self.stops_supported

    def create_stop_order(self, symbol, side, amount, stop_price, params=None):
        if not self.stops_supported:
            raise ccxt.NotSupported("no stops")
        oid = self._id()
        self.stops[oid] = {"id": oid, "status": "open", "filled": 0.0, "amount": amount, "stopPrice": stop_price,
                           "side": side, "params": dict(params or {})}
        self.calls.append(("stop", side, amount, stop_price, dict(params or {})))
        return dict(self.stops[oid])

    def trigger_stop(self, order_id, price, filled=None):
        order = self.stops[order_id]
        order.update(status="closed", filled=order["amount"] if filled is None else filled, average=price,
                     fee={"cost": 0.0, "currency": "USDT"})

    def amount_to_precision(self, symbol, amount):
        return round(amount, 8)

    def market_limits(self, symbol):
        return {"min_amount": self.min_amount, "min_cost": None}

    def fetch_balance(self):
        return {"free": {"USDT": 10_000.0}, "total": {"USDT": 10_000.0}}

    def fetch_last_price(self, symbol):
        return self.price


def _live(state, ex, market_type="swap"):
    return LiveExecutionClient(state, ex, market_type=market_type, quote_currency="USDT", fee_rate_estimate=0.0)


def _open(live, qty=1.0):
    return live.open_position("BTC/USDT", "long", qty, 100.0, stop_loss=95.0, take_profit=110.0, atr=2.0)


def _stop_id(state, pos):
    info = state.get_state(f"stop_order:{pos['id']}")
    return info and info["id"]


# ------------------------------------------------------------ partial fills
def test_partial_close_keeps_remainder_open_and_finishes_later(state):
    ex = FakeExchange(stops_supported=False)
    live = _live(state, ex)
    pos = _open(live)

    ex.fills = [0.6]
    ex.price = 110.0
    after = live.close_position(pos, 110.0, "take_profit")
    assert after["status"] == "open" and after["quantity"] == pytest.approx(0.4)
    assert live.pending_close_reason(after) == "take_profit"

    ex.price = 108.0
    closed = live.close_position(after, 108.0, "take_profit")
    assert closed["status"] == "closed" and closed["exit_reason"] == "take_profit"
    assert closed["pnl"] == pytest.approx(0.6 * 10 + 0.4 * 8)  # both parts, no fees in this test
    assert ex.calls[-1][:3] == ("market", "sell", 0.4)
    assert live.pending_close_reason(closed) is None


def test_unfilled_close_leaves_position_open(state):
    ex = FakeExchange(stops_supported=False)
    live = _live(state, ex)
    pos = _open(live)
    ex.fills = [0.0]
    after = live.close_position(pos, 100.0, "manual")
    assert after["status"] == "open" and after["quantity"] == pytest.approx(1.0)
    assert live.pending_close_reason(after) == "manual"


def test_remainder_below_exchange_minimum_is_closed_as_dust(state):
    ex = FakeExchange(stops_supported=False, min_amount=0.01)
    live = _live(state, ex)
    pos = _open(live)
    ex.fills = [0.995]
    assert live.close_position(pos, 100.0, "manual")["status"] == "closed"


def test_engine_retries_a_pending_close_even_when_price_is_inside_the_levels(state):
    ex = FakeExchange(stops_supported=False)
    live = _live(state, ex)
    engine = BotEngine(Config(symbols=["BTC/USDT"]), state, ex, live, RiskManager(state.get_all_settings),
                       sleep_fn=lambda s: None)
    pos = _open(live)
    ex.fills = [0.5]
    live.close_position(pos, 100.0, "manual")
    engine._enforce_stops("BTC/USDT", 101.0)  # between stop 95 and target 110
    closed = state.get_position(pos["id"])
    assert closed["status"] == "closed" and closed["exit_reason"] == "manual"


def test_partial_entry_fill_records_filled_amount_and_zero_fill_opens_nothing(state):
    ex = FakeExchange(stops_supported=False)
    live = _live(state, ex)
    ex.fills = [0.7]
    assert _open(live)["quantity"] == pytest.approx(0.7)
    ex.fills = [0.0]
    assert _open(live) is None
    assert len(state.get_open_positions()) == 1


# ------------------------------------------------------- exchange stops
def test_entry_places_reduce_only_stop_at_position_stop(state):
    ex = FakeExchange()
    pos = _open(_live(state, ex))
    assert ex.calls[-1] == ("stop", "sell", pytest.approx(1.0), pytest.approx(95.0), {"reduceOnly": True})
    assert _stop_id(state, pos) in ex.stops


def test_spot_stop_has_no_reduce_only(state):
    ex = FakeExchange()
    _open(_live(state, ex, market_type="spot"))
    assert ex.calls[-1][0] == "stop" and ex.calls[-1][4] == {}


def test_trailing_move_replaces_the_exchange_stop(state):
    ex = FakeExchange()
    live = _live(state, ex)
    pos = _open(live)
    old = _stop_id(state, pos)
    state.update_position(pos["id"], stop_loss=102.0)
    live.on_stop_moved(state.get_position(pos["id"]))
    assert ex.stops[old]["status"] == "canceled"
    new = _stop_id(state, pos)
    assert new != old and ex.stops[new]["stopPrice"] == pytest.approx(102.0)


def test_bot_close_cancels_the_stop_before_the_market_order(state):
    ex = FakeExchange()
    live = _live(state, ex)
    pos = _open(live)
    sid = _stop_id(state, pos)
    live.close_position(pos, 100.0, "manual")
    kinds = [c[0] for c in ex.calls]
    assert kinds.index("cancel") < len(kinds) - 1 and kinds[-1] == "market"
    assert ex.stops[sid]["status"] == "canceled"
    assert state.get_state(f"stop_order:{pos['id']}") is None


def test_close_does_not_sell_twice_when_exchange_stop_already_filled(state):
    ex = FakeExchange()
    live = _live(state, ex)
    pos = _open(live)
    ex.trigger_stop(_stop_id(state, pos), price=94.9)
    closed = live.close_position(pos, 94.0, "stop_loss")
    assert closed["status"] == "closed" and closed["exit_reason"] == "exchange_stop"
    assert closed["exit_price"] == pytest.approx(94.9)
    assert [c for c in ex.calls if c[0] == "market" and c[1] == "sell"] == []


def test_restart_records_a_stop_that_filled_while_the_bot_was_off(state):
    ex = FakeExchange()
    pos = _open(_live(state, ex))
    ex.trigger_stop(_stop_id(state, pos), price=94.5)

    restarted = _live(state, ex)  # fresh client on the same DB
    restarted.sync_protective_stops()
    closed = state.get_position(pos["id"])
    assert closed["status"] == "closed" and closed["exit_reason"] == "exchange_stop"
    assert closed["exit_price"] == pytest.approx(94.5)
    assert closed["pnl"] == pytest.approx(-5.5)


def test_sync_replaces_a_stop_cancelled_on_the_exchange(state):
    ex = FakeExchange()
    live = _live(state, ex)
    pos = _open(live)
    old = _stop_id(state, pos)
    ex.stops[old]["status"] = "canceled"
    live.sync_protective_stops()
    new = _stop_id(state, pos)
    assert new != old and ex.stops[new]["status"] == "open"
    assert state.get_position(pos["id"])["status"] == "open"


def test_sync_places_a_stop_for_positions_without_one(state):
    ex = FakeExchange()
    live = _live(state, ex)
    pid = state.open_position(symbol="BTC/USDT", side="long", quantity=1.0, entry_price=100, stop_loss=95,
                              take_profit=110, mode="live")
    live.sync_protective_stops()
    assert _stop_id(state, {"id": pid}) in ex.stops


def test_partial_close_re_protects_the_remainder(state):
    ex = FakeExchange()
    live = _live(state, ex)
    pos = _open(live)
    ex.fills = [0.6]
    live.close_position(pos, 100.0, "manual")
    stop = ex.stops[_stop_id(state, pos)]
    assert stop["status"] == "open" and stop["amount"] == pytest.approx(0.4)


def test_unsupported_stops_warn_once_and_keep_bot_managed_stops(state):
    ex = FakeExchange(stops_supported=False)
    live = _live(state, ex)
    pos = _open(live)
    live.sync_protective_stops()
    warnings = [e for e in state.get_events() if "not supported" in e["message"]]
    assert len(warnings) == 1
    assert live.close_position(pos, 94.0, "stop_loss")["status"] == "closed"


def test_setting_off_places_no_exchange_stop(state):
    state.set_setting("exchange_stop_enabled", False)
    ex = FakeExchange()
    _open(_live(state, ex))
    assert not any(c[0] == "stop" for c in ex.calls)


def test_refused_stop_is_retried_later_not_every_loop(state):
    ex = FakeExchange()

    def refuse(*a, **k):
        ex.calls.append(("stop-refused",))
        raise ccxt.InvalidOrder("stop price too close")

    ex.create_stop_order = refuse
    live = _live(state, ex)
    _open(live)
    live.sync_protective_stops()
    live.sync_protective_stops()
    assert [c for c in ex.calls if c[0] == "stop-refused"] == [("stop-refused",)]
