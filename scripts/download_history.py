"""Download real historical OHLCV candles for backtesting.

Primary source: Binance's public data archive (https://data.binance.vision),
monthly spot kline files. It needs no API key and, unlike api.binance.com,
is reachable from US-based machines such as GitHub Actions runners.
Fallback (``--source ccxt``): paged ``fetch_ohlcv`` through ccxt from any
exchange that serves the pair (for example ``--exchange kraken``).

Output: one ``<BASE><QUOTE>-<timeframe>.csv.gz`` per pair and timeframe with
columns ``timestamp,open,high,low,close,volume`` (timestamp = candle open,
UTC milliseconds), readable by ``backtest.py --csv``. Only complete months
are downloaded, so every candle is closed.

    python scripts/download_history.py --symbols BTC/USDT,ETH/USDT --timeframes 1h,4h --start 2021-01
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd

ARCHIVE = "https://data.binance.vision/data/spot/monthly/klines/{pair}/{tf}/{pair}-{tf}-{month}.zip"
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def months_between(start: str, end: str) -> List[str]:
    """Inclusive list of 'YYYY-MM' strings."""
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def last_complete_month(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return (pd.Period(now.strftime("%Y-%m"), freq="M") - 1).strftime("%Y-%m")


def pair_code(symbol: str) -> str:
    return symbol.replace("/", "").split(":")[0].upper()


def _get(url: str, attempts: int = 4) -> Optional[bytes]:
    for n in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None  # month not listed yet / pair did not exist
            err = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            err = exc
        time.sleep(2 ** n)
    raise RuntimeError(f"download failed: {url}: {err}")


def parse_kline_csv(raw: bytes) -> pd.DataFrame:
    """Binance kline CSV (with or without header) -> COLUMNS, timestamps in ms."""
    df = pd.read_csv(io.BytesIO(raw), header=None, usecols=range(6), names=COLUMNS)
    if not str(df.iloc[0, 0]).strip().isdigit():  # header row present
        df = df.iloc[1:]
    df = df.astype(float)
    ts = df["timestamp"].astype("int64")
    df["timestamp"] = ts.where(ts < 10**14, ts // 1000)  # 2025+ files use microseconds
    return df


def download_binance_archive(symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
    pair = pair_code(symbol)
    frames = []
    for month in months_between(start, end):
        raw = _get(ARCHIVE.format(pair=pair, tf=timeframe, month=month))
        if raw is None:
            continue
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            frames.append(parse_kline_csv(zf.read(zf.namelist()[0])))
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    return _clean(pd.concat(frames))


def download_ccxt(symbol: str, timeframe: str, start: str, end: str, exchange_id: str) -> pd.DataFrame:
    import ccxt

    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    tf_ms = ex.parse_timeframe(timeframe) * 1000
    since = int(pd.Timestamp(start + "-01", tz="UTC").timestamp() * 1000)
    until = int((pd.Timestamp(end + "-01", tz="UTC") + pd.offsets.MonthBegin(1)).timestamp() * 1000)
    rows: list = []
    while since < until:
        batch = ex.fetch_ohlcv(symbol, timeframe, since, 1000)
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1][0] + tf_ms
        if nxt <= since:
            break
        since = nxt
    df = pd.DataFrame(rows, columns=COLUMNS)
    return _clean(df[df["timestamp"] < until])


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.astype(float).astype({"timestamp": "int64"})
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return df[(df["high"] >= df["low"]) & (df["close"] > 0)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT")
    ap.add_argument("--timeframes", default="1h,4h")
    ap.add_argument("--start", default="2021-01", help="First month, YYYY-MM")
    ap.add_argument("--end", default=None, help="Last month, YYYY-MM (default: last complete month)")
    ap.add_argument("--out", default="data/history")
    ap.add_argument("--source", choices=["binance-archive", "ccxt"], default="binance-archive")
    ap.add_argument("--exchange", default="kraken", help="ccxt exchange id for --source ccxt")
    ap.add_argument("--force", action="store_true", help="Re-download files that already exist")
    args = ap.parse_args(argv)

    end = args.end or last_complete_month()
    os.makedirs(args.out, exist_ok=True)
    failed = 0
    for symbol in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        for tf in [t.strip() for t in args.timeframes.split(",") if t.strip()]:
            path = os.path.join(args.out, f"{pair_code(symbol)}-{tf}.csv.gz")
            if os.path.exists(path) and not args.force:
                print(f"{path}: exists, skipped")
                continue
            try:
                if args.source == "ccxt":
                    df = download_ccxt(symbol, tf, args.start, end, args.exchange)
                else:
                    df = download_binance_archive(symbol, tf, args.start, end)
            except Exception as exc:  # keep going with the other pairs
                print(f"{symbol} {tf}: FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
                failed += 1
                continue
            if df.empty:
                print(f"{symbol} {tf}: no data", file=sys.stderr)
                failed += 1
                continue
            df.to_csv(path, index=False, compression="gzip")
            first = datetime.fromtimestamp(df["timestamp"].iloc[0] / 1000, tz=timezone.utc).date()
            last = datetime.fromtimestamp(df["timestamp"].iloc[-1] / 1000, tz=timezone.utc).date()
            print(f"{path}: {len(df)} candles {first} -> {last}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
