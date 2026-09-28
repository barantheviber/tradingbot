"""Streamlit dashboard.

    streamlit run dashboard/app.py

Reads the same .env and SQLite database as the bot. It never places orders
itself: "Kapat" buttons enqueue a command that the running bot executes
within ~1 second, so all order flow stays in one process.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from dashboard.logic import apply_setting_changes, dashboard_is_local_only  # noqa: E402
from config import DEFAULT_SETTINGS, load_config  # noqa: E402
from exchange_client import ExchangeClient  # noqa: E402
from performance import compute_performance  # noqa: E402
from risk_manager import daily_loss_pct, unrealized_pnl  # noqa: E402
from state_manager import LegacyDatabaseError, StateManager  # noqa: E402
from strategy import StrategyParams, compute_indicators  # noqa: E402

st.set_page_config(page_title="Trading Bot", page_icon="📈", layout="wide")

# The dashboard has no login but can close positions and edit settings, so it
# only runs when Streamlit listens on loopback (see .streamlit/config.toml).
if not dashboard_is_local_only(st.get_option("server.address")) and \
        os.getenv("DASHBOARD_ALLOW_REMOTE", "").strip().lower() != "true":
    st.error("Panel yalnızca bu bilgisayardan açılabilir: şifresi yok ama pozisyon kapatıp ayar değiştirebiliyor. "
             "Depo kök klasöründen `streamlit run dashboard/app.py` ile başlatın (.streamlit/config.toml "
             "adresi 127.0.0.1 yapar) veya `--server.address 127.0.0.1` ekleyin.")
    st.stop()


@st.cache_resource
def get_config():
    return load_config(os.path.join(ROOT, ".env"))


@st.cache_resource
def get_state(db_path: str) -> StateManager:
    state = StateManager(db_path if os.path.isabs(db_path) else os.path.join(ROOT, db_path))
    state.seed_default_settings(DEFAULT_SETTINGS)
    return state


@st.cache_resource
def get_exchange(_config) -> ExchangeClient:
    # public data only - the dashboard never needs API keys
    client = ExchangeClient.from_config(_config, public_only=True)
    client.max_retries = min(client.max_retries, 2)  # keep the UI responsive when the exchange is down
    return client


@st.cache_data(ttl=15, show_spinner=False)
def load_candles(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    return get_exchange(get_config()).fetch_ohlcv(symbol, timeframe, limit)


config = get_config()
try:
    state = get_state(config.db_path)
except LegacyDatabaseError as exc:
    st.error(str(exc))
    st.stop()
mode = config.mode

# ------------------------------------------------------------------ sidebar
st.sidebar.title("📈 Trading Bot")
st.sidebar.markdown(f"**Mod:** {'🟢 PAPER' if mode == 'paper' else '🔴 LIVE'}  \n"
                    f"**Borsa:** {config.exchange_id}{' (testnet)' if config.use_testnet else ''}  \n"
                    f"**Zaman dilimi:** {config.timeframe}")
symbol = st.sidebar.selectbox("Sembol", config.symbols)
n_candles = st.sidebar.slider("Mum sayısı", 100, 1000, 300, step=50)
auto = st.sidebar.toggle("Otomatik yenile", value=True)
refresh_sec = st.sidebar.number_input("Yenileme (sn)", 5, 300, 15)


def _fmt_age(ts: float) -> str:
    age = time.time() - ts
    return f"{age:.0f} sn önce" if age < 120 else f"{age / 60:.0f} dk önce"


def render_status() -> None:
    hb = state.get_state("heartbeat") or {}
    status = (state.get_state("bot_status") or {}).get("status", "unknown")
    status = {"running": "ÇALIŞIYOR", "stopped": "DURDU"}.get(status, "BİLİNMİYOR")
    open_pos = state.get_open_positions(mode=mode)
    prices = hb.get("prices", {})
    upnl = sum(unrealized_pnl(p["side"], p["entry_price"], prices.get(p["symbol"], p["entry_price"]), p["quantity"])
               for p in open_pos)
    equity = hb.get("equity")
    day_start = state.get_day_start_equity(mode) if equity is not None else None

    c = st.columns(6)
    stale = hb.get("ts") and time.time() - hb["ts"] > max(120, config.poll_interval_sec * 4)
    c[0].metric("Bot", status, _fmt_age(hb["ts"]) if hb.get("ts") else "heartbeat yok",
                delta_color="inverse" if stale else "normal")
    c[1].metric("Özsermaye", f"{equity:,.2f}" if equity is not None else "-")
    c[2].metric("Gerçekleşen PnL", f"{state.realized_pnl(mode):,.2f}")
    c[3].metric("Gerçekleşmemiş PnL", f"{upnl:,.2f}")
    c[4].metric("Açık pozisyon", f"{len(open_pos)} / {state.get_setting('max_open_positions')}")
    if day_start and equity is not None:
        loss = daily_loss_pct(day_start, equity)
        limit = float(state.get_setting("daily_loss_limit_pct", 5.0))
        c[5].metric("Günlük zarar", f"{loss:.2f}%", f"limit {limit:.1f}%",
                    delta_color="inverse" if loss >= limit else "off")
    else:
        c[5].metric("Günlük zarar", "-")
    if stale:
        st.warning("Bot heartbeat'i eski görünüyor: bot çalışıyor mu? (`python main.py`)")


def render_chart() -> None:
    try:
        df = load_candles(symbol, config.timeframe, n_candles)
    except Exception as exc:
        st.error(f"Mum verisi alınamadı: {type(exc).__name__}: {exc}")
        return
    if df.empty:
        st.info("Veri yok.")
        return
    params = StrategyParams.from_settings(state.get_all_settings())
    ind = compute_indicators(df, params)
    ind["time"] = pd.to_datetime(ind["timestamp"], unit="ms", utc=True)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(x=ind["time"], open=ind["open"], high=ind["high"], low=ind["low"],
                                 close=ind["close"], name=symbol), row=1, col=1)
    fig.add_trace(go.Scatter(x=ind["time"], y=ind["ema_trend"], name=f"EMA{params.ema_trend_period}",
                             line=dict(width=1.5, color="#f5a623")), row=1, col=1)
    fig.add_trace(go.Scatter(x=ind["time"], y=ind["donchian_high"], name="Donchian üst",
                             line=dict(width=1, dash="dot", color="#7f8c8d")), row=1, col=1)
    fig.add_trace(go.Scatter(x=ind["time"], y=ind["donchian_low"], name="Donchian alt",
                             line=dict(width=1, dash="dot", color="#7f8c8d")), row=1, col=1)
    fig.add_trace(go.Bar(x=ind["time"], y=ind["volume"], name="Hacim", marker_color="#5b6b7f"), row=2, col=1)

    sig = ind[ind["long_signal"] | ind["short_signal"]]
    if not sig.empty:
        fig.add_trace(go.Scatter(x=sig["time"], y=sig["close"], mode="markers", name="Sinyal",
                                 marker=dict(symbol="star", size=10, color="#8e44ad")), row=1, col=1)

    trades = [t for t in state.get_trades(mode=mode, limit=500) if t["symbol"] == symbol]
    if trades:
        tdf = pd.DataFrame(trades)
        tdf["time"] = pd.to_datetime(tdf["timestamp"], utc=True)
        tdf = tdf[tdf["time"] >= ind["time"].iloc[0]]
        for side, color, marker in (("buy", "#2ecc71", "triangle-up"), ("sell", "#e74c3c", "triangle-down")):
            part = tdf[tdf["side"] == side]
            if not part.empty:
                fig.add_trace(go.Scatter(x=part["time"], y=part["price"], mode="markers",
                                         name="Alış" if side == "buy" else "Satış",
                                         marker=dict(symbol=marker, size=12, color=color)), row=1, col=1)

    for p in state.get_open_positions(mode=mode, symbol=symbol):
        for level, color, label in ((p["entry_price"], "#3498db", "Giriş"), (p["stop_loss"], "#e74c3c", "SL"),
                                    (p["take_profit"], "#2ecc71", "TP")):
            if level:
                fig.add_hline(y=level, line_dash="dash", line_color=color, annotation_text=f"{label} #{p['id']}",
                              row=1, col=1)

    fig.update_layout(height=620, margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", y=1.04), template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)


def render_positions() -> None:
    st.subheader("Açık pozisyonlar")
    positions = state.get_open_positions(mode=mode)
    prices = (state.get_state("heartbeat") or {}).get("prices", {})
    if not positions:
        st.caption("Açık pozisyon yok.")
    else:
        header = st.columns([0.6, 1.2, 0.7, 1, 1, 1, 1, 1, 1.1, 0.9])
        for col, name in zip(header, ["#", "Sembol", "Yön", "Miktar", "Giriş", "Fiyat", "SL", "TP", "PnL", ""]):
            col.markdown(f"**{name}**")
        for p in positions:
            price = prices.get(p["symbol"], p["entry_price"])
            pnl = unrealized_pnl(p["side"], p["entry_price"], price, p["quantity"]) - (p["fees"] or 0)
            cols = st.columns([0.6, 1.2, 0.7, 1, 1, 1, 1, 1, 1.1, 0.9])
            cols[0].write(p["id"])
            cols[1].write(p["symbol"])
            cols[2].write("🟢 long" if p["side"] == "long" else "🔴 short")
            cols[3].write(f"{p['quantity']:.6g}")
            cols[4].write(f"{p['entry_price']:.6g}")
            cols[5].write(f"{price:.6g}")
            cols[6].write(f"{p['stop_loss']:.6g}")
            cols[7].write(f"{p['take_profit']:.6g}" if p["take_profit"] else "-")
            cols[8].write(f"{pnl:,.2f}")
            if cols[9].button("Kapat", key=f"close_{p['id']}", type="primary"):
                state.enqueue_command("close_position", {"position_id": p["id"]})
                st.toast(f"#{p['id']} için kapatma emri kuyruğa alındı; bot ~1 sn içinde işleyecek.")
        if st.button("Tüm pozisyonları kapat"):
            state.enqueue_command("close_all")
            st.toast("Tümünü kapat komutu kuyruğa alındı.")

    pending = state.get_pending_commands()
    if pending:
        st.info(f"{len(pending)} komut botun işlemesini bekliyor (bot çalışmıyorsa işlenmez).")


def render_pnl() -> None:
    st.subheader("PnL özeti")
    closed = state.get_closed_positions(mode=mode, limit=100000)
    stats = compute_performance(closed, config.paper_starting_balance if mode == "paper" else 0.0)
    c = st.columns(5)
    c[0].metric("İşlem", stats["trades"])
    c[1].metric("Kazanma oranı", f"{stats['win_rate_pct']:.1f}%")
    c[2].metric("Toplam PnL", f"{stats['total_pnl']:,.2f}")
    pf = stats["profit_factor"]
    c[3].metric("Profit factor", "∞" if pf == float("inf") else f"{pf:.2f}")
    c[4].metric("Maks. drawdown", f"{stats['max_drawdown']:,.2f}", f"{stats['max_drawdown_pct']:.2f}%",
                delta_color="off")
    if closed:
        cdf = pd.DataFrame(closed).sort_values(["closed_at", "id"])
        cdf["kümülatif PnL"] = cdf["pnl"].cumsum()
        st.line_chart(cdf.set_index("closed_at")["kümülatif PnL"], height=200)
        st.dataframe(
            cdf[["id", "symbol", "side", "quantity", "entry_price", "exit_price", "pnl", "fees", "exit_reason",
                 "opened_at", "closed_at"]].iloc[::-1],
            use_container_width=True, hide_index=True, height=260,
        )


def render_logs() -> None:
    st.subheader("İşlem / karar logu")
    categories = ["hepsi", "trade", "decision", "signal", "risk", "trailing", "error", "lifecycle", "restore",
                  "reconcile", "performance"]
    cat = st.selectbox("Kategori", categories, key="log_cat")
    events = state.get_events(limit=400)
    if cat != "hepsi":
        events = [e for e in events if e["category"] == cat]
    lines = [f"{e['timestamp']} {e['level']:<8} {e['category']:<10} {e['symbol'] or '-':<12} {e['message']}"
             for e in events[:250]]
    st.code("\n".join(lines) or "(boş)", language="text")


def render_settings() -> None:
    st.subheader("Strateji / risk parametreleri (canlı)")
    st.caption("Değişiklikler veritabanına yazılır; bot bir sonraki kapanmış mumda yeni değerleri kullanır.")
    rows = state.get_settings_with_meta()
    with st.form("settings_form"):
        new_values = {}
        cols = st.columns(3)
        for i, row in enumerate(rows):
            key, value, help_text = row["key"], row["value"], row["description"]
            col = cols[i % 3]
            if isinstance(value, bool):
                new_values[key] = col.checkbox(key, value=value, help=help_text)
            elif isinstance(value, int):
                new_values[key] = col.number_input(key, value=value, step=1, help=help_text)
            elif isinstance(value, float):
                new_values[key] = col.number_input(key, value=value, step=0.1, format="%.4f", help=help_text)
            else:
                new_values[key] = col.text_input(key, value=str(value), help=help_text)
        if st.form_submit_button("Kaydet", type="primary"):
            current = {r["key"]: r["value"] for r in rows}
            changed, errors = apply_setting_changes(state, current, new_values)
            if changed:
                st.success("Güncellendi: " + ", ".join(changed))
                state.log_event("INFO", "settings", "Settings changed from dashboard", data={"keys": changed})
            for e in errors:
                st.error(e)
            if not changed and not errors:
                st.info("Değişiklik yok.")


def live_section() -> None:
    render_status()
    render_chart()
    left, right = st.columns([1.35, 1])
    with left:
        render_positions()
        render_pnl()
    with right:
        render_logs()
    st.caption(f"Son güncelleme: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")


if auto:
    st.fragment(run_every=int(refresh_sec))(live_section)()
else:
    if st.sidebar.button("Yenile"):
        st.cache_data.clear()
    live_section()

st.divider()
render_settings()
