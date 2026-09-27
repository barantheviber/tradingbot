# Gerçek Veriyle Backtest Raporu

_Tarih: 27 Eylül 2026. Veri: Binance spot, Ocak 2021 ile Ağustos 2026 arası (son tamamlanmış ay)._

## Kısa özet

- **Eski varsayılan ayarlar gerçek veride para kaybettiriyordu.** 5 parite × 3 zaman diliminden oluşan 15 piyasanın 13'ünde tüm dönem zararla kapandı. Kâr faktörü 0,66, kazanma oranı %30,5 oldu. Hiçbir piyasa test dönemini (Temmuz 2024 sonrası) kârla bitiremedi.
- **Asıl sorun maliyetlerdi.** Stoplar dar (1,5 ATR), kâr al hedefi yakın (2R) olduğu için işlemler ortalama 8 mum sürüyordu. Her işlemde ödenen %0,1 + %0,1 komisyon ve kayma, planlanan riskin yaklaşık üçte birini yiyordu.
- **Yeni varsayılanlar** trend takibine dayanıyor: geniş stop (3 ATR), uzak kâr hedefi (10R), 5 ATR'lik trailing stop ve RSI üst sınırının kaldırılması. **4 saatlik** grafikte, ayarların hiç görmediği test döneminde 5 paritenin 5'inde de küçük bir kâr çıktı. Ortalama getiri +%4,3, Sharpe 0,42, kâr faktörü 1,60 oldu.
- **15 dakikalık grafik her iki ayarla da ağır zarar ediyor.** Burada maliyetler kazancı aşıyor. Botu 15 dakikada çalıştırmayın. Varsayılan zaman dilimi 1 saatten **4 saate** çekildi.
- **1 saatlik grafikte sonuç karışık.** Test döneminde ortalama +%3,4 çıktı, ama bu büyük ölçüde XRP'nin tek başına +%35 kazancından geliyor. 5 paritenin 3'ü zararda.
- **Bu sonuçlar kâr garantisi değildir.** Yeni ayarlar da sadece hareketsiz tutmaya (al-ve-tut) göre çok daha az getiri sağladı. 2022 gibi düşüş yıllarında küçük zarar etti. Ayrıntılar aşağıda.

## Yöntem

**Veri.** BTC, ETH, SOL, BNB ve XRP'nin USDT paritelerinde 15 dakika, 1 saat ve 4 saatlik mumlar kullanıldı. Kaynak, Binance'in herkese açık arşivi (data.binance.vision). Sadece tamamlanmış aylar alındı, yani bütün mumlar kapanmış mumlar.

**Simülasyon (`backtest.py`).** Canlı botla aynı `strategy.compute_indicators` ve `risk_manager` kodu kullanıldı. Kurallar şunlar:

- Sinyal mumun kapanışında üretilir, emir bir sonraki mumun açılışında dolar. İleriye bakma (look-ahead) yok.
- Her dolumda %0,10 komisyon (taker) ve 5 baz puan kayma ödenir.
- Stop ile çıkışlarda 5 baz puan ek kayma var, çünkü canlı bot stopu ancak bir sonraki fiyat sorgusunda fark ediyor.
- Aynı mumda hem stop hem hedef görülürse önce stopun tetiklendiği varsayılır. Fiyat seviyenin ötesinde açılırsa (boşluk) dolum açılış fiyatından yapılır.
- 10 USDT'nin altındaki emirler atlanır (borsanın asgari emir tutarı).
- Pozisyon boyutu canlıdaki gibi hesaplanır: işlem başı risk %1 ve sembol başına en fazla %25 maruziyet. Günlük %5 zarar limiti de uygulanır.
- Her piyasa 10.000 USDT ile ve tek başına test edildi. Canlı bot birkaç sembolü aynı bakiyeyle işler; bu yüzden bu rakamlar portföy sonucu değildir.

**Aşırı uyumdan (overfitting) korunma.**

- Veri ikiye bölündü. **Geliştirme dönemi** Ocak 2021 ile Haziran 2024 arası, **test dönemi** Temmuz 2024 ile Ağustos 2026 arası.
- Bütün denemeler geliştirme dönemi içinde yapıldı: 1 saat ve 4 saat, 5 parite. Geliştirme dönemi ayrıca dört dilime bölündü (2021, 2022, 2023, 2024'ün ilk yarısı). Sadece dilimlerin çoğunda eski ayarları geçen ayarlar aday oldu.
- **Toplam 69 ayar kombinasyonu denendi.** Bu kadar çok deneme, şans eseri iyi görünen bir ayar seçme riskini artırır. Rakamları bu gözle okuyun.
- Test dönemine sadece bir kez, son iki adayla bakıldı. Sonra hiçbir ayar değiştirilmedi.
- Maliyet varsayımları hiç düşürülmedi.

## Sonuçlar

Tablolardaki değerler 5 paritenin ortalamasıdır. "Kârlı" sütunu, kârla kapanan parite sayısını gösterir.

### Eski ve yeni varsayılanlar: test dönemi (Temmuz 2024 ile Ağustos 2026 arası)

| Zaman dilimi | Ayar | İşlem | Kazanma % | Kâr faktörü | Getiri % | Maks. düşüş % | Sharpe | Kârlı |
|---|---|---|---|---|---|---|---|---|
| 4h | eski | 94 | 24,7 | 0,51 | -3,74 | 4,66 | -0,82 | 0/5 |
| 4h | **yeni** | 92 | 31,3 | 1,60 | **+4,30** | 6,48 | **0,42** | **5/5** |
| 1h | eski | 374 | 32,8 | 0,67 | -4,90 | 6,53 | -0,95 | 0/5 |
| 1h | yeni | 437 | 29,7 | 1,10 | +3,44 | 10,96 | 0,03 | 2/5 |
| 15m | eski | 1727 | 24,5 | 0,38 | -25,74 | 26,14 | -4,83 | 0/5 |
| 15m | yeni | 1746 | 25,4 | 0,64 | -21,75 | 26,44 | -2,13 | 1/5 |

Aynı dönemde al-ve-tut ortalama +%34 getirdi. ETH ve SOL tek başına yaklaşık %30 düştü, XRP ise %190 yükseldi.

### Tüm dönem (Ocak 2021 ile Ağustos 2026 arası)

| Zaman dilimi | Ayar | İşlem | Kazanma % | Kâr faktörü | Getiri % | Maks. düşüş % (en kötü) | Sharpe | Kârlı |
|---|---|---|---|---|---|---|---|---|
| 4h | eski | 243 | 31,3 | 0,75 | -4,77 | 8,21 (12,37) | -0,38 | 1/5 |
| 4h | **yeni** | 268 | 33,5 | 1,87 | **+24,01** | 9,23 (13,13) | **0,71** | **5/5** |
| 1h | eski | 994 | 34,5 | 0,77 | -10,66 | 15,79 (19,98) | -0,68 | 1/5 |
| 1h | yeni | 1121 | 30,0 | 1,09 | +7,76 | 15,56 (20,88) | 0,19 | 3/5 |
| 15m | eski | 4317 | 25,7 | 0,47 | -52,44 | 53,24 (58,10) | -3,87 | 0/5 |
| 15m | yeni | 4469 | 25,3 | 0,72 | -46,61 | 53,40 (59,63) | -1,34 | 0/5 |

Tüm dönem getirisinin büyük kısmı geliştirme döneminden geliyor. Ayarlar bu dönemde seçildiği için oradaki rakamlar olduğundan iyi görünür. Güvenilir rakam, bir önceki tablodaki test dönemi sonuçlarıdır.

### 4 saatlik grafikte yıl yıl (yeni ayarlar, 5 paritenin ortalaması)

| Yıl | Getiri % | Maks. düşüş % | Kâr faktörü | Kârlı | Al-ve-tut % |
|---|---|---|---|---|---|
| 2021 | +11,78 | 4,61 | 4,68 | 5/5 | +2494 |
| 2022 | -1,12 | 3,77 | 0,64 | 1/5 | -68 |
| 2023 | +6,02 | 5,85 | 2,24 | 3/5 | +255 |
| 2024 | +3,70 | 6,26 | 1,73 | 3/5 | +124 |
| 2025 | +2,26 | 3,79 | 2,26 | 4/5 | -9 |
| 2026 (8 ay) | -0,13 | 3,25 | 0,98 | 3/5 | -18 |

Strateji sadece long işlem açıyor (spotta short yok). Yükselen piyasada kazanıyor, düşen piyasada (2022) az işlem açıp küçük zarar ediyor. Eski ayarlar 2022'de biraz daha iyiydi (+%1,3).

### 4 saatlik grafikte pariteler, test dönemi (yeni ayarlar)

| Parite | İşlem | Kazanma % | Kâr faktörü | Getiri % | Maks. düşüş % | Al-ve-tut % |
|---|---|---|---|---|---|---|
| BTC | 18 | 50,0 | 2,52 | +8,51 | 3,33 | +23,9 |
| ETH | 17 | 17,6 | 1,05 | +0,44 | 6,39 | -29,5 |
| SOL | 18 | 33,3 | 1,59 | +3,90 | 5,06 | -30,2 |
| BNB | 22 | 31,8 | 1,04 | +0,48 | 8,17 | +18,1 |
| XRP | 17 | 23,5 | 1,78 | +8,18 | 9,44 | +188,2 |

## Ne değişti

| Ayar | Eski | Yeni | Neden |
|---|---|---|---|
| `atr_sl_multiplier` | 1,5 | **3,0** | Dar stop, olağan dalgalanmada tetikleniyordu. Maliyetin risk içindeki payını da yarıya indiriyor. Pozisyon boyutu otomatik küçülür; işlem başı risk (%1) aynı kalır. |
| `risk_reward_ratio` | 2,0 | **10,0** | 2R hedef, kazançları erken kesiyordu. Kazanan işlemler artık çoğunlukla trailing stop veya trend dönüşüyle kapanıyor. |
| `trailing_atr_multiplier` | 2,0 | **5,0** | Trende nefes alacak alan bırakıyor. |
| `rsi_long_max` | 70 | **100** | Verilerde en güçlü devam hareketleri RSI 70'in üstündeki kırılımlardan geldi. Bu sınır onları eliyordu. Momentum katmanı artık sadece RSI ≥ 45 şartını arıyor. |
| `TIMEFRAME` | 1h | **4h** | Test döneminde kazanan tek zaman dilimi. |

Değişmeyenler: çok katmanlı teyit yapısı (EMA200 trend filtresi + en az 3 teyit), işlem başı risk %1, günlük zarar limiti %5, sembol başına %25 maruziyet, en fazla 3 pozisyon, varsayılan paper modu ve canlıya geçiş onayı.

**Yeni, varsayılan olarak kapalı ayarlar** (panelden canlı açılabilir):

- `ema_slope_bars`: trend EMA'sının son N mumda yükselmesini şart koşar.
- `adx_min`: giriş için en düşük ADX (trend gücü).
- `min_atr_pct`: çok sakin piyasayı atlar.

Geliştirme döneminde tek başına veya yeni ayarlarla birlikte sonucu belirgin biçimde iyileştirmedikleri için kapalı bırakıldılar.

**Migration.** Veritabanı şeması değişmedi, ama `state_manager` **migration 2** eklendi. Bu migration, `rsi_long_max`, `atr_sl_multiplier`, `risk_reward_ratio` ve `trailing_atr_multiplier` hâlâ eski varsayılan değerindeyse onları yeni değere çeker. Elle değiştirdiğiniz değerlere dokunmaz. Risk yüzdesi, zarar limiti, maruziyet ve mod ayarlarına hiç dokunmaz. Bot, masaüstü ya da telefon uygulaması bir sonraki açılışta bunu kendiliğinden yapar.

## Bu sonuçlar ne anlama geliyor, ne anlama gelmiyor

**Anlama geldiği:**

- Eski ayarlar maliyetler yüzünden neredeyse her piyasada ve her yılda para kaybettiriyordu. Onlarla canlıya geçmek kötü bir fikir olurdu.
- Trend takibine dönük ayarlar 4 saatlik grafikte, görmediği bir dönemde de küçük ama tutarlı bir üstünlük gösterdi.

**Anlama gelmediği:**

- **Kâr garantisi değildir.** Test dönemi yaklaşık 26 ay ve parite başına 20 civarında işlem içeriyor. Bu az bir örnek; sonuçlar şansla da açıklanabilir.
- **Al-ve-tut'u geçmiyor.** Yeni ayarlar parayı zamanın yaklaşık %12-20'sinde piyasada tutuyor ve düşüşleri küçük tutuyor. Karşılığında yükselişlerin çoğunu kaçırıyor.
- **69 deneme yapıldı.** Test dönemine tek bakış bu riski azaltır ama ortadan kaldırmaz.
- **Gerçek işlemler farklı olabilir.** Backtest mum verisiyle yapıldı. Canlıda fiyat sorgusunun gecikmesi, borsa kesintileri, likidite ve API hataları sonucu kötüleştirebilir.
- **Rakamlar portföy sonucu değildir.** Her parite ayrı ayrı test edildi.

## Öneriler

1. **4 saatlik grafikte en az 6 ay paper modda çalıştırın.** Bu ayarlarla parite başına ayda ortalama 1 işlem bile çıkmaz. Sabırlı olun; sonuçları buradaki test dönemi rakamlarıyla karşılaştırın.
2. **15 dakika ve altını kullanmayın.** Maliyetler her ayarda kazancı aşıyor.
3. **Canlıya geçerseniz küçük başlayın ve BNB ile komisyon indirimi kullanın.** Maliyet bu stratejinin en büyük düşmanı.
4. **Denemeye değer fikirler (paper modda):**
   - Düşüş piyasalarında daha az işlem için `ema_slope_bars=50` deneyebilirsiniz. Geliştirme döneminde 2022 kaybını azalttı, ama genel sonucu iyileştirmedi.
   - Portföy düzeyinde bir test (aynı bakiyeyle birden çok parite) yapılabilir. Bu henüz yapılmadı.
5. **Her hafta yeni veriyle kontrol edin.** GitHub Actions'daki "Real-data backtest" iş akışı her pazartesi yeni ay verisiyle tekrar çalışır; elle de başlatılabilir. Sonuçlar çalışmanın özet sayfasında ve `backtest-data` dalında durur.

## Kendiniz çalıştırmak için

```bash
python scripts/download_history.py --timeframes 1h,4h --start 2021-01           # data/history/ klasörüne indirir
python scripts/backtest_matrix.py --data data/history --split 2024-07-01 --yearly \
    --variant "eski:atr_sl_multiplier=1.5,risk_reward_ratio=2,trailing_atr_multiplier=2,rsi_long_max=70"
python backtest.py --csv data/history/BTCUSDT-4h.csv.gz --trades-csv islemler.csv
```

> ⚠️ **Bu bot kâr garantisi vermez, yatırım tavsiyesi değildir.** Geçmiş performans (backtest dahil) gelecekteki sonuçları göstermez. Canlıya geçmeden önce uzun süre paper trading ve mümkünse testnet ile doğrulayın. Kaybetmeyi göze alamayacağınız parayla işlem yapmayın.
