# tradingbot

Python + [ccxt](https://github.com/ccxt/ccxt) tabanlı, modüler kripto trading botu. Varsayılan olarak **paper trading** (kağıt üzerinde, gerçek para olmadan) çalışır.

## Mimari

```
config.py            -> tüm ayarlar (env değişkenlerinden okunur)
exchange_client.py    -> ccxt sarmalayıcısı, exponential backoff + jitter ile retry
strategy.py           -> sinyal üretimi (execution'dan bağımsız, backtest'te de kullanılır)
risk_manager.py       -> pozisyon boyutlandırma, SL/TP, trailing stop, günlük drawdown limiti
state_manager.py      -> SQLite: pozisyonlar, işlem geçmişi, canlı düzenlenebilir parametreler
execution/
  base.py             -> BaseExecutionClient arayüzü (ortak loglama + performans özeti)
  paper.py            -> PaperExecutionClient (simüle fill)
  live.py             -> LiveExecutionClient (gerçek emir, exchange_client üzerinden)
bot_engine.py          -> ana döngü: sadece KAPANMIŞ mumlarda sinyal üretir, SIGINT/SIGTERM ile düzgün kapanır
dashboard/app.py       -> Streamlit + Plotly: canlı grafik, açık pozisyonlar, PnL, log terminali, canlı parametre paneli
backtest.py            -> hızlı, look-ahead-safe walk-forward backtest scripti
main.py                -> giriş noktası
tests/                 -> risk_manager, state_manager, strategy için birim testleri
```

## Kurulum

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# .env dosyasını kendi ayarlarınla düzenle (borsa, sembol, risk parametreleri, API anahtarları)
```

`.env` dosyası asla repoya eklenmez (`.gitignore` içinde). API anahtarların sadece `.env` üzerinden okunur; koda gömülmez, hiçbir yerde loglanmaz.

## Çalıştırma

### Botu başlat (paper trading, varsayılan)

```bash
python main.py
```

`PAPER_TRADING=True` iken hiçbir gerçek emir gönderilmez; fill'ler `execution/paper.py` içinde simüle edilir ve bakiye SQLite'ta (`data/trading_bot.sqlite3`) tutulur.

### Canlıya geçiş

Bilinçli, ayrı bir adımdır:

1. `.env` içinde `EXCHANGE_API_KEY` ve `EXCHANGE_API_SECRET` değerlerini gir.
2. `PAPER_TRADING=False` yap.
3. İlk seferde `EXCHANGE_SANDBOX=True` ile borsanın testnet'inde doğrula, sonra `False` yap.

### Dashboard'u başlat

```bash
streamlit run dashboard/app.py
```

Canlı mum grafiği (EMA200 + Donchian kanalı ile), açık pozisyonlar (manuel kapatma butonlu), PnL özeti, karar/işlem log terminali ve strateji/risk parametrelerini canlı düzenleyebileceğin form burada.

### Backtest

```bash
python backtest.py --symbol BTC/USDT --timeframe 15m --limit 1500
# ya da yerel bir CSV ile:
python backtest.py --csv path/to/ohlcv.csv
```

CSV formatı: `timestamp,open,high,low,close,volume` (timestamp ms cinsinden, ccxt `fetch_ohlcv` ile aynı).

### Testler

```bash
pytest
```

### Sözdizimi kontrolü

```bash
python -m py_compile config.py exchange_client.py strategy.py risk_manager.py state_manager.py bot_engine.py main.py backtest.py execution/*.py dashboard/app.py
```

## Strateji katmanı

Tek indikatöre güvenilmez; bir sinyal için tüm katmanlar aynı yönde uyuşmalıdır:

1. **Trend filtresi** - EMA200'e göre fiyat konumu.
2. **Momentum** - RSI, ayarlanabilir bir aralıkta (varsayılan 40-70) "sağlıklı" kabul edilir.
3. **MACD kesişimi + hacim teyidi** - MACD histogramının sıfırı kesmesi, hacmin hareketli ortalamasının üzerinde olmasıyla teyit edilir.
4. **Volatilite kırılımı** - Donchian kanalının önceki üst/alt bandının kırılması, ATR ile birlikte pozisyon boyutlandırmada kullanılır.

Tüm parametreler `state_manager` üzerinden canlı değiştirilebilir (dashboard'daki form ya da `state_manager.set_setting(key, value)`); koda gömülü değildir.

## Risk yönetimi

- Pozisyon boyutu: `risk_amount / stop_distance`, burada `risk_amount = equity * risk_per_trade_pct / 100` ve `stop_distance = ATR * atr_sl_multiplier`.
- TP, `risk_reward_ratio` (varsayılan 2:1) ile stop mesafesinin katı kadar ötede.
- Trailing stop yalnızca kârı koruyan yönde ilerler (`risk_manager.update_trailing_stop`).
- Günlük toplam zarar `max_daily_drawdown_pct` (varsayılan %5) aşarsa o gün yeni pozisyon açılışı durur; UTC gece yarısında otomatik sıfırlanır.
- `max_concurrent_positions` ve `max_exposure_per_symbol_pct` ile eşzamanlı pozisyon sayısı ve sembol başına maruziyet sınırlanır.

## Şema migration'ları

`state_manager.py` içindeki `_migrations` listesi, `__init__` içinde bir kere çalışır ve `meta.schema_version` ile hangi migration'ların uygulandığını takip eder. Yeni bir şema değişikliği eklerken:

1. Yeni bir `_migration_00N_...` metodu ekle (idempotent olmalı, örn. `ALTER TABLE` öncesi `PRAGMA table_info` ile kolon kontrolü).
2. `self._migrations` listesine sona ekle.
3. Var olan veritabanları bir sonraki `StateManager(...)` çağrısında otomatik olarak bu migration'ı çalıştırır; eski veriler korunur.

Bu teslimde uygulanan migration'lar:
- `001_initial_schema`: `positions`, `trades`, `settings`, `event_log` tabloları.
- `002_add_positions_meta`: `positions` tablosuna `meta` (JSON) kolonu.

## Dayanıklılık

- Tüm ağ çağrıları `exchange_client.py` üzerinden, exponential backoff + jitter ile retry edilir. Retryable hatalar (`NetworkError`, `RateLimitExceeded`, `DDoSProtection`, `ExchangeNotAvailable`, `RequestTimeout`) ile retryable olmayanlar (`AuthenticationError`, `InsufficientFunds`, `InvalidOrder`, `PermissionDenied`, `BadSymbol`) ayrı ele alınır.
- Yapılandırılmış loglama: hem dosyaya (`logs/trading_bot.log`) hem konsola; her karar ve hata net şekilde loglanır, aynı zamanda `state_manager.event_log` tablosuna da yazılır (dashboard'daki log terminali buradan beslenir).
- Bot çöküp yeniden başlarsa, açık pozisyonlar `state_manager`'dan geri yüklenir (`bot_engine._restore_open_positions`).
- `SIGINT`/`SIGTERM` ile düzgün kapanma: ana döngü tek uzun `sleep` yerine 1 saniyelik artışlarla uyur, sinyal geldiği an döngüden çıkar.

## Varsaydığım API'ler / entegrasyon noktaları

İleride gerçek kodla bir sapma olursa kolayca düzeltebilmen için, bu ilk teslimde kendi içinde tutarlı varsaydığım isimler:

- `state_manager.StateManager.get_setting(key, default=None)` / `set_setting(key, value)` / `get_all_settings()` / `seed_default_settings(defaults)`
- `state_manager.StateManager.open_position/close_position/update_position_stop/get_open_positions/get_position`
- `state_manager.StateManager.record_trade/get_trade_history/realized_pnl_since`
- `state_manager.StateManager.log_event/get_recent_events`
- `execution.base.BaseExecutionClient.open_position/close_position/get_account_equity/performance_summary`
- `strategy.generate_signal(df, StrategyParams) -> Signal` (`Signal.side`, `.reasons`, `.indicators`)
- `risk_manager.compute_position_size/update_trailing_stop/check_exposure_limit/check_max_positions`

---

**Uyarı:** Bu bot kâr garantisi vermez ve yatırım tavsiyesi değildir. Canlıya geçmeden önce uzun süre paper trading ile ve mümkünse borsanın testnet ortamıyla doğrulama yapılmalıdır. Kripto para ticareti önemli finansal risk taşır; kaybetmeyi göze alamayacağın parayla işlem yapma.
