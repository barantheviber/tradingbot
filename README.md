# tradingbot

Python + [ccxt](https://github.com/ccxt/ccxt) tabanlı, modüler bir kripto trading botu.
Varsayılan olarak **paper trading** modunda çalışır; canlıya geçiş bilinçli, ayrı bir adımdır.

> ⚠️ **UYARI:** Bu bot kâr garantisi vermez ve yatırım tavsiyesi değildir. Kripto piyasaları çok
> oynaktır ve tüm sermayenizi kaybedebilirsiniz. Canlıya geçmeden önce botu uzun süre paper trading
> modunda ve mümkünse borsanın testnet ortamında doğrulayın. Kullanımdan doğan tüm sorumluluk size aittir.

## Mimari

```
config.py            Ortam ayarları (.env) + canlı parametrelerin başlangıç değerleri
logging_setup.py     Yapılandırılmış log: konsol + JSON satırlı dönen dosya, API anahtarı maskeleme
exchange_client.py   ccxt sarmalayıcısı: exponential backoff + jitter, retry / fail-fast ayrımı
strategy.py          Saf sinyal fonksiyonları (I/O yok) - canlı bot ve backtest aynı kodu kullanır
risk_manager.py      ATR ile pozisyon boyutu, SL/TP, trailing stop, günlük zarar limiti, maruziyet
state_manager.py     SQLite: pozisyonlar, işlem geçmişi, canlı ayarlar, olay logu, migration
performance.py       Ortak performans özeti (kazanma oranı, profit factor, drawdown...)
execution/
  base.py            BaseExecutionClient: ortak açma/kapama, PnL, loglama, performans özeti
  paper.py           PaperExecutionClient: slippage + komisyon simülasyonu
  live.py            LiveExecutionClient: gerçek emirler, hassasiyet/min. limit kontrolü, mutabakat
bot_engine.py        Ana döngü: sadece kapanmış mumlar, 1 sn'lik uykularla düzgün kapanma
dashboard/app.py     Streamlit + Plotly paneli
main.py              Giriş noktası
backtest.py          Geçmiş veride hızlı sağlama
tests/               Birim testleri (risk, boyutlandırma, state, strateji, retry, engine)
```

### Strateji (çok katmanlı teyit)

1. **Trend filtresi (zorunlu):** kapanış EMA200'ün üstünde (long) / altında (short).
2. **Momentum:** RSI ayarlanabilir bir aralıkta (aşırı alım/satımı kovalamaz).
3. **MACD + hacim:** son N kapanmış mumda MACD/sinyal kesişimi, MACD hâlâ doğru tarafta ve hacim
   ortalamanın belirli katı üzerinde.
4. **Volatilite kırılımı:** kapanış, önceki N mumun Donchian kanalını (isteğe bağlı ATR tamponuyla) aşıyor.

Sinyal = trend filtresi + 2-4 numaralı katmanlardan en az `min_confirmations` tanesi (varsayılan 3,
yani hepsi). Pozisyon, fiyat EMA trend çizgisinin ters tarafında kapanırsa da kapatılır
(`exit_on_trend_flip`). Short varsayılan olarak kapalıdır (`allow_short`); spot piyasada canlıda short açılmaz.

**Look-ahead yok:** borsadan gelen son (henüz kapanmamış) mum atılır, Donchian kanalı ve hacim
ortalaması bir mum kaydırılarak hesaplanır ve bot her kapanmış mumu yalnızca bir kez değerlendirir
(son işlenen mum SQLite'ta tutulur, yeniden başlatmada aynı mum tekrar işlenmez). Bir testte, gelecek
mumlar eklendiğinde geçmiş sinyallerin değişmediği doğrulanıyor.

### Risk yönetimi

- **Pozisyon boyutu:** `(özsermaye × risk_per_trade_pct) / |giriş − stop|`, stop mesafesi = ATR × `atr_sl_multiplier`.
- **TP:** stop mesafesi × `risk_reward_ratio` (varsayılan 2:1).
- **Trailing stop:** fiyat `trailing_activation_r` × R lehimize gidince devreye girer; en yüksek (long)
  / en düşük (short) fiyattan ATR × `trailing_atr_multiplier` uzakta durur ve **yalnızca kârı koruyan
  yönde** hareket eder.
- **Günlük zarar limiti:** UTC gün başı özsermayesine göre zarar `daily_loss_limit_pct`'i (varsayılan %5)
  aşarsa yeni pozisyon açılmaz; UTC gece yarısında yeni gün kaydıyla otomatik sıfırlanır.
- **Maruziyet:** `max_open_positions` ve sembol başına `max_symbol_exposure_pct` (özsermaye yüzdesi) sınırı.
  Sembol başına aynı anda tek pozisyon açılır.
- **Kill switch:** `trading_enabled=false` yeni girişleri durdurur, açık pozisyonların SL/TP'si çalışmaya devam eder.

Tüm strateji/risk parametreleri SQLite `settings` tablosundadır ve **canlı değiştirilebilir**
(dashboard, `python main.py --set ...` veya doğrudan `StateManager.set_setting`). Bot her mumda
güncel değerleri okur. `config.py` içindeki `DEFAULT_SETTINGS` sadece ilk çalıştırmadaki başlangıç
değerleridir; sizin değiştirdiğiniz değerlerin üzerine yazılmaz.

### Dayanıklılık

- Tüm ağ çağrıları `ExchangeClient.call` üzerinden retry + exponential backoff + jitter ile yapılır.
  `NetworkError` / `RateLimitExceeded` / `DDoSProtection` tekrar denenir; `AuthenticationError`,
  `InsufficientFunds`, `InvalidOrder` vb. hemen hata verir. Kimlik doğrulama hatasında bot durur.
- **Emirler:** çift emir riskine karşı `create_order` yalnızca emrin kesin reddedildiği rate-limit
  hatalarında tekrar denenir; zaman aşımında bir sonraki döngüde durum yeniden değerlendirilir.
- Açık pozisyonlar SQLite'tan geri yüklenir; canlı modda borsa bakiyesiyle karşılaştırılır (mutabakat
  uyarısı).
- Loglar: konsol (okunabilir) + `logs/tradingbot.jsonl` (JSON satırları, 5 MB × 5 dönen dosya).
  Her sinyal değerlendirmesi, karar, işlem ve hata ayrıca SQLite `event_log` tablosuna yazılır ve
  dashboard'daki log terminalinde görünür. API anahtarları hiçbir log çıktısına yazılmaz (maskeleme filtresi).

> **Not:** SL/TP ve trailing stop bot tarafından (yazılımsal) uygulanır; bot çalışmıyorsa tetiklenmez.

## Kurulum

Python 3.10+ gerekir.

```bash
git clone https://github.com/barantheviber/tradingbot.git
cd tradingbot
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # sonra .env'i düzenleyin
```

## Çalıştırma

```bash
# 1) Testler ve sözdizimi kontrolü
python -m py_compile $(git ls-files '*.py')
python -m pytest -q

# 2) Backtest (strateji mantığının hızlı sağlaması)
python backtest.py --synthetic 3000                         # internetsiz, sentetik veri
python backtest.py --symbol BTC/USDT --timeframe 1h --days 180
python backtest.py --csv veri.csv --db data/tradingbot.db   # canlı ayarlarla
python backtest.py --days 365 --set min_confirmations=2 --set risk_reward_ratio=3 --trades-csv trades.csv

# 3) Bot (varsayılan: paper trading)
python main.py                 # sürekli çalışır, Ctrl+C / SIGTERM ile düzgün kapanır
python main.py --once          # tek döngü (duman testi)

# 4) Dashboard (ayrı bir terminalde)
streamlit run dashboard/app.py

# Ayarları komut satırından görmek / değiştirmek
python main.py --show-settings
python main.py --set risk_per_trade_pct=0.5 --set max_open_positions=2
```

Backtest'te sinyal mumun kapanışında hesaplanır, emir bir sonraki mumun açılışında dolar; aynı mumda
hem SL hem TP'ye değilirse (muhafazakâr olarak) önce SL varsayılır.

### Dashboard

- Canlı mum grafiği (EMA, Donchian kanalı, sinyaller, alış/satış işaretleri, açık pozisyonların giriş/SL/TP çizgileri)
- Açık pozisyonlar tablosu ve her satırda **Kapat** butonu (+ tümünü kapat)
- PnL özeti, kümülatif PnL grafiği ve kapanmış işlemler
- İşlem/karar log terminali (kategori filtresi)
- Strateji/risk parametrelerini canlı düzenleme paneli

Dashboard hiçbir zaman kendisi emir göndermez ve API anahtarı kullanmaz: **Kapat** butonu SQLite'taki
komut kuyruğuna bir kayıt ekler, çalışan bot bunu ~1 saniye içinde işler. Bu nedenle manuel kapatma için
botun çalışıyor olması gerekir.

## Canlıya geçiş (bilinçli adım)

1. Uzun süre paper modda çalıştırın ve sonuçları inceleyin.
2. Mümkünse önce testnet: `.env` içinde `USE_TESTNET=true` ve testnet API anahtarları.
3. Borsada **para çekme yetkisi olmayan**, mümkünse IP kısıtlı bir API anahtarı oluşturun.
4. `.env` içinde:
   ```
   PAPER_TRADING=false
   LIVE_TRADING_CONFIRM=I_UNDERSTAND_THE_RISKS
   API_KEY=...
   API_SECRET=...
   ```
   İkisi birden ayarlanmadan bot canlı modda başlamaz.
5. Küçük `risk_per_trade_pct` ve `max_symbol_exposure_pct` değerleriyle başlayın.

Paper ve canlı pozisyonlar veritabanında `mode` sütunuyla ayrılır; yine de her mod için ayrı bir
`DB_PATH` kullanmanız önerilir.

## Önceki sürümden geçiş

Bu sürüm, kısa süre main'de duran önceki bot sürümünün (PR #2) yerine geçer. O sürümü kurup
çalıştırdıysanız:

1. **`.env` dosyasını yeniden oluşturun:** `cp .env.example .env` ve değerleri tekrar girin. Değişken
   adları değişti (ör. `EXCHANGE_API_KEY` → `API_KEY`, `EXCHANGE_SANDBOX` → `USE_TESTNET`,
   `SYMBOL` → `SYMBOLS`). Eski adlar okunmaz; bot açılışta bunlar için uyarı yazar.
2. **Eski veritabanı taşınamaz:** önceki sürüm `data/trading_bot.sqlite3` dosyasını kullanıyordu, şeması
   farklıdır. Yeni sürüm varsayılan olarak `data/tradingbot.db` kullanır, yani ikisi çakışmaz. `DB_PATH`
   eski dosyayı gösterirse bot açılmaz ve açıklayıcı bir hata verir. Eski dosyada sadece paper
   verisi varsa silebilirsiniz: `rm data/trading_bot.sqlite3*`.
3. **Canlı pozisyon açtıysanız:** önce o pozisyonları borsada (veya eski sürümle) kapatın. Yeni bot
   eski veritabanındaki pozisyonları bilmez ve onları yönetmez.
4. **Strateji/risk ayarları** artık `.env`'den okunmaz (`EMA_TREND_PERIOD`, `RSI_LOWER`, `RISK_PER_TRADE_PCT`...).
   Dashboard'daki ayar panelinden veya `python main.py --set anahtar=değer` ile girin
   (`python main.py --show-settings` tüm anahtarları listeler).

## Borsa değiştirme

`.env` içinde `EXCHANGE_ID` herhangi bir ccxt borsa kimliği olabilir (`binance`, `bybit`, `okx`,
`kucoin`...). Vadeli işlemler için `MARKET_TYPE=future` / `swap` ve uygun sembol formatı
(ör. `BTC/USDT:USDT`) kullanın.

## Şema değişiklikleri (migration)

`StateManager.__init__` tek seferlik `_run_migrations()` çağırır; `schema_version` tablosuna bakarak
eksik migration'ları sırayla, her biri kendi transaction'ında uygular. Yeni bir şema değişikliği için
`state_manager.py` içindeki `MIGRATIONS` listesine yeni bir `(versiyon, fonksiyon)` ekleyin ve yalnızca
eklemeli değişiklik yapın (ör. `add_column_if_missing(conn, "positions", "strategy", "TEXT DEFAULT 'x'")`).
Yayınlanmış bir migration'ı asla değiştirmeyin. Mevcut şema versiyonu: **1**.

---

> ⚠️ **Bu bot kâr garantisi vermez, yatırım tavsiyesi değildir.** Geçmiş performans (backtest dahil)
> gelecekteki sonuçları göstermez. Canlıya geçmeden önce uzun süre paper trading ve mümkünse testnet ile
> doğrulayın; yalnızca kaybetmeyi göze alabileceğiniz parayla işlem yapın.
