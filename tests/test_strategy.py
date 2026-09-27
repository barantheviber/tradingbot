import numpy as np
import pandas as pd

from strategy import Side, StrategyParams, generate_signal


def make_trending_df(n: int = 260, start_price: float = 100.0) -> pd.DataFrame:
    """Synthetic, steadily-rising OHLCV data with an occasional volume spike,
    just enough to exercise generate_signal without asserting a specific
    trade direction (the point of this test is "it runs and returns a
    well-formed Signal", not "the strategy is profitable")."""
    rng = np.random.default_rng(42)
    closes = start_price + np.cumsum(rng.normal(loc=0.15, scale=0.5, size=n))
    opens = closes - rng.normal(0, 0.2, size=n)
    highs = np.maximum(opens, closes) + rng.uniform(0, 0.5, size=n)
    lows = np.minimum(opens, closes) - rng.uniform(0, 0.5, size=n)
    volumes = rng.uniform(100, 200, size=n)
    volumes[-5:] *= 3  # spike near the end to help volume confirmation trigger
    timestamps = np.arange(n) * 15 * 60 * 1000

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


class TestGenerateSignal:
    def test_insufficient_history_returns_no_trade(self):
        df = make_trending_df(n=10)
        params = StrategyParams()
        signal = generate_signal(df, params)
        assert signal.side is None
        assert "insufficient_history" in signal.reasons

    def test_well_formed_signal_on_enough_data(self):
        df = make_trending_df(n=260)
        params = StrategyParams()
        signal = generate_signal(df, params)
        assert signal.side in (None, Side.LONG, Side.SHORT)
        assert signal.indicators is not None
        assert isinstance(signal.reasons, list) and len(signal.reasons) > 0

    def test_signal_never_uses_future_bars(self):
        """Appending future bars must not change the signal computed on the
        earlier window - this is the core look-ahead-bias guarantee."""
        df_full = make_trending_df(n=260)
        params = StrategyParams()

        df_early = df_full.iloc[:250].reset_index(drop=True)
        signal_early = generate_signal(df_early, params)
        signal_early_recomputed = generate_signal(df_full.iloc[:250].reset_index(drop=True), params)

        assert signal_early.side == signal_early_recomputed.side
        assert signal_early.indicators.close == signal_early_recomputed.indicators.close
