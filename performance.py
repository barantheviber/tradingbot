"""Performance statistics shared by the execution clients, dashboard and backtest."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping


def compute_performance(closed_positions: Iterable[Mapping[str, Any]], starting_equity: float = 0.0) -> Dict[str, Any]:
    """Summary over closed positions (each needs ``pnl``; ordered or with ``closed_at``)."""
    rows = [p for p in closed_positions if p.get("pnl") is not None]
    rows.sort(key=lambda p: (str(p.get("closed_at") or ""), p.get("id") or 0))
    pnls = [float(p["pnl"]) for p in rows]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)

    equity, peak, max_dd, max_dd_pct = starting_equity, starting_equity, 0.0, 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, dd / peak * 100.0)

    n = len(pnls)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (len(wins) / n * 100.0) if n else 0.0,
        "total_pnl": sum(pnls),
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (-gross_loss / len(losses)) if losses else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
        "expectancy": (sum(pnls) / n) if n else 0.0,
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "fees": sum(float(p.get("fees") or 0.0) for p in rows),
    }


def format_performance(stats: Mapping[str, Any]) -> str:
    pf = stats["profit_factor"]
    return (
        f"trades={stats['trades']} win_rate={stats['win_rate_pct']:.1f}% total_pnl={stats['total_pnl']:.2f} "
        f"avg_win={stats['avg_win']:.2f} avg_loss={stats['avg_loss']:.2f} "
        f"profit_factor={'inf' if pf == float('inf') else f'{pf:.2f}'} "
        f"max_dd={stats['max_drawdown']:.2f} ({stats['max_drawdown_pct']:.2f}%) fees={stats['fees']:.2f}"
    )
