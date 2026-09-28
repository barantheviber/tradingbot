# Gerçek Veriyle Backtest Raporu

_Tarih: 27 Eylül 2026, walk-forward testi 28 Eylül 2026'da eklendi. Veri: Binance spot, Ocak 2021 ile Ağustos 2026 arası (son tamamlanmış ay)._

## Kısa özet

- **Eski varsayılan ayarlar gerçek veride para kaybettiriyordu.** 5 parite × 3 zaman diliminden oluşan 15 piyasanın 13'ünde tüm dönem zararla kapandı. Kâr faktörü 0,66, kazanma oranı %30,5 oldu. Hiçbir piyasa test dönemini (Temmuz 2024 sonrası) kârla bitiremedi.
- **Asıl sorun maliyetlerdi.** Stoplar dar (1,5 ATR), kâr al hedefi yakın (2R) olduğu için işlemler ortalama 8 mum sürüyordu. Her işlemde ödenen %0,1 + %0,1 komisyon ve kayma, planlanan riskin yaklaşık üçte birini yiyordu.
- **Yeni varsayılanlar** trend takibine dayanıyor: geniş stop (3 ATR), uzak kâr hedefi (10R), 5 ATR'lik trailing stop ve RSI üst sınırının kaldırılması. **4 saatlik** grafikte, ayarların hiç görmediği test döneminde 5 paritenin 5'inde de küçük bir kâr çıktı. Ortalama getiri +%4,3, Sharpe 0,44, kâr faktörü 1,62 oldu.
- **15 dakikalık grafik her iki ayarla da ağır zarar ediyor.** Burada maliyetler kazancı aşıyor. Botu 15 dakikada çalıştırmayın. Varsayılan zaman dilimi 1 saatten **4 saate** çekildi.
- **1 saatlik grafikte sonuç karışık.** Test döneminde ortalama +%3,4 çıktı, ama bu büyük ölçüde XRP'nin tek başına +%35 kazancından geliyor. 5 paritenin 3'ü zararda.
- **Güvenilirlik kontrolleri karışık ama çöküş yok.** Ayarlar bir adım oynatılınca 4 saatlik sonuç kârda kalıyor; sivri, şans eseri bulunmuş bir tepe görünmüyor. Ayarlamada hiç kullanılmayan 9 altcoinde yeni ayarlar tüm dönemde eskilerden iyi (+%10,5 ve -%1,4). Ama son iki yılda bu paritelerde sonuç başa baş (+%0,6).
- **Walk-forward testi (kayan pencereler) ayarları doğruladı, değiştirmedi.** 14 paritede, ayarların hiç görmediği Temmuz 2024 sonrası dönemde şu anki ayarlar ortalama +%2,0 kazandırdı, al-ve-tut -%7 kaybetti. Ayarları her 6 ayda yeniden seçmek daha iyi sonuç vermedi, bu yüzden varsayılanlar aynı kaldı. Ayrıntılar "Güvenilirlik kontrolleri" bölümünde.
- **Bu sonuçlar kâr garantisi değildir.** Yeni ayarlar da sadece hareketsiz tutmaya (al-ve-tut) göre çok daha az getiri sağladı. 2022 gibi düşüş yıllarında küçük zarar etti. Ayrıntılar aşağıda.

## Yöntem

**Veri.** BTC, ETH, SOL, BNB ve XRP'nin USDT paritelerinde 15 dakika, 1 saat ve 4 saatlik mumlar kullanıldı. Kaynak, Binance'in herkese açık arşivi (data.binance.vision). Sadece tamamlanmış aylar alındı, yani bütün mumlar kapanmış mumlar.

**Simülasyon (`backtest.py`).** Canlı botla aynı `strategy.compute_indicators` ve `risk_manager` kodu kullanıldı. Kurallar şunlar:

- Sinyal mumun kapanışında üretilir, emir bir sonraki mumun açılışında dolar. İleriye bakma (look-ahead) yok.
- Her dolumda %0,10 komisyon (taker) ve 5 baz puan kayma ödenir.
- Stop ile çıkışlarda 5 baz puan ek kayma var, çünkü canlı bot stopu ancak bir sonraki fiyat sorgusunda fark ediyor.
- Aynı mumda hem stop hem hedef görülürse önce stopun tetiklendiği varsayılır. Fiyat seviyenin ötesinde açılırsa (boşluk) dolum açılış fiyatından yapılır.
- 10 USDT'nin altındaki emirler atlanır (borsanın asgari emir tutarı).
- Pozisyon boyutu canlıdaki gibi hesaplanır: işlem başı risk %1 (komisyon ve kayma dahil) ve sembol başına en fazla %25 maruziyet. Günlük %5 zarar limiti de uygulanır.
- Her piyasa 10.000 USDT ile ve tek başına test edildi. Canlı bot birkaç sembolü aynı bakiyeyle işler; bu yüzden bu rakamlar portföy sonucu değildir.

**Aşırı uyumdan (overfitting) korunma.**

- Veri ikiye bölündü. **Geliştirme dönemi** Ocak 2021 ile Haziran 2024 arası, **test dönemi** Temmuz 2024 ile Ağustos 2026 arası.
- Bütün denemeler geliştirme dönemi içinde yapıldı: 1 saat ve 4 saat, 5 parite. Geliştirme dönemi ayrıca dört dilime bölündü (2021, 2022, 2023, 2024'ün ilk yarısı). Sadece dilimlerin çoğunda eski ayarları geçen ayarlar aday oldu.
- **Toplam 69 ayar kombinasyonu denendi.** Bu kadar çok deneme, şans eseri iyi görünen bir ayar seçme riskini artırır. Rakamları bu gözle okuyun.
- Test dönemine sadece bir kez, son iki adayla bakıldı. Sonra hiçbir strateji ayarı değiştirilmedi. Maliyet dahil boyutlandırma sadece riski düşüren bir düzeltme; aynı test dönemiyle bir kez daha kontrol edildi.
- Maliyet varsayımları hiç düşürülmedi.

## Sonuçlar

Tablolardaki değerler 5 paritenin ortalamasıdır. "Kârlı" sütunu, kârla kapanan parite sayısını gösterir.

### Eski ve yeni varsayılanlar: test dönemi (Temmuz 2024 ile Ağustos 2026 arası)

| Zaman dilimi | Ayar | İşlem | Kazanma % | Kâr faktörü | Getiri % | Maks. düşüş % | Sharpe | Kârlı |
|---|---|---|---|---|---|---|---|---|
| 4h | eski | 94 | 24,7 | 0,51 | -3,74 | 4,66 | -0,82 | 0/5 |
| 4h | **yeni** | 92 | 31,3 | 1,62 | **+4,29** | 6,13 | **0,44** | **5/5** |
| 1h | eski | 374 | 32,8 | 0,67 | -4,90 | 6,53 | -0,95 | 0/5 |
| 1h | yeni | 437 | 29,7 | 1,10 | +3,39 | 10,78 | 0,04 | 2/5 |
| 15m | eski | 1727 | 24,5 | 0,38 | -25,74 | 26,14 | -4,83 | 0/5 |
| 15m | yeni | 1746 | 25,4 | 0,64 | -21,85 | 26,43 | -2,14 | 1/5 |

Aynı dönemde al-ve-tut ortalama +%34 getirdi. ETH ve SOL tek başına yaklaşık %30 düştü, XRP ise %190 yükseldi.

### Tüm dönem (Ocak 2021 ile Ağustos 2026 arası)

| Zaman dilimi | Ayar | İşlem | Kazanma % | Kâr faktörü | Getiri % | Maks. düşüş % (en kötü) | Sharpe | Kârlı |
|---|---|---|---|---|---|---|---|---|
| 4h | eski | 243 | 31,3 | 0,75 | -4,77 | 8,21 (12,37) | -0,38 | 1/5 |
| 4h | **yeni** | 268 | 33,5 | 1,89 | **+23,51** | 8,78 (12,46) | **0,72** | **5/5** |
| 1h | eski | 994 | 34,5 | 0,77 | -10,66 | 15,79 (19,98) | -0,68 | 1/5 |
| 1h | yeni | 1121 | 30,0 | 1,09 | +7,62 | 15,07 (20,39) | 0,19 | 3/5 |
| 15m | eski | 4317 | 25,7 | 0,47 | -52,44 | 53,24 (58,10) | -3,87 | 0/5 |
| 15m | yeni | 4469 | 25,3 | 0,72 | -46,60 | 53,16 (59,57) | -1,35 | 0/5 |

Tüm dönem getirisinin büyük kısmı geliştirme döneminden geliyor. Ayarlar bu dönemde seçildiği için oradaki rakamlar olduğundan iyi görünür. Güvenilir rakam, bir önceki tablodaki test dönemi sonuçlarıdır.

### 4 saatlik grafikte yıl yıl (yeni ayarlar, 5 paritenin ortalaması)

| Yıl | Getiri % | Maks. düşüş % | Kâr faktörü | Kârlı | Al-ve-tut % |
|---|---|---|---|---|---|
| 2021 | +11,38 | 4,43 | 4,69 | 5/5 | +2494 |
| 2022 | -1,04 | 3,59 | 0,64 | 1/5 | -68 |
| 2023 | +5,93 | 5,63 | 2,27 | 3/5 | +255 |
| 2024 | +3,56 | 5,98 | 1,73 | 3/5 | +124 |
| 2025 | +2,25 | 3,63 | 2,27 | 4/5 | -9 |
| 2026 (8 ay) | -0,03 | 3,09 | 0,99 | 3/5 | -18 |

Strateji sadece long işlem açıyor (spotta short yok). Yükselen piyasada kazanıyor, düşen piyasada (2022) az işlem açıp küçük zarar ediyor. Eski ayarlar 2022'de biraz daha iyiydi (+%1,3).

### 4 saatlik grafikte pariteler, test dönemi (yeni ayarlar)

| Parite | İşlem | Kazanma % | Kâr faktörü | Getiri % | Maks. düşüş % | Al-ve-tut % |
|---|---|---|---|---|---|---|
| BTC | 18 | 50,0 | 2,50 | +8,10 | 3,15 | +23,9 |
| ETH | 17 | 17,6 | 1,04 | +0,38 | 6,00 | -29,5 |
| SOL | 18 | 33,3 | 1,66 | +4,09 | 4,77 | -30,2 |
| BNB | 22 | 31,8 | 1,08 | +0,86 | 7,81 | +18,1 |
| XRP | 17 | 23,5 | 1,81 | +8,00 | 8,93 | +188,2 |

## Ne değişti

| Ayar | Eski | Yeni | Neden |
|---|---|---|---|
| `atr_sl_multiplier` | 1,5 | **3,0** | Dar stop, olağan dalgalanmada tetikleniyordu. Maliyetin risk içindeki payını da yarıya indiriyor. Pozisyon boyutu otomatik küçülür; işlem başı risk (%1) aynı kalır. |
| `risk_reward_ratio` | 2,0 | **10,0** | 2R hedef, kazançları erken kesiyordu. Kazanan işlemler artık çoğunlukla trailing stop veya trend dönüşüyle kapanıyor. |
| `trailing_atr_multiplier` | 2,0 | **5,0** | Trende nefes alacak alan bırakıyor. |
| `rsi_long_max` | 70 | **100** | Verilerde en güçlü devam hareketleri RSI 70'in üstündeki kırılımlardan geldi. Bu sınır onları eliyordu. Momentum katmanı artık sadece RSI ≥ 45 şartını arıyor. |
| `TIMEFRAME` | 1h | **4h** | Test döneminde kazanan tek zaman dilimi. |
| `round_trip_cost_pct` (yeni) | yok | **0,35** | Pozisyon boyutu artık giriş ve çıkış komisyonu ile kaymayı da hesaba katıyor. Böylece stopta toplam kayıp ayarlanan %1 riski aşmıyor. Bu ayar riski sadece düşürür. |

Değişmeyenler: çok katmanlı teyit yapısı (EMA200 trend filtresi + en az 3 teyit), işlem başı risk %1, günlük zarar limiti %5, sembol başına %25 maruziyet, en fazla 3 pozisyon, varsayılan paper modu ve canlıya geçiş onayı.

**Maliyet dahil pozisyon boyutu.** Önceden pozisyon boyutu sadece stop mesafesine göre hesaplanıyordu. Stop tetiklenince komisyon ve kayma yüzünden gerçek kayıp %1'in biraz üstüne çıkıyordu. Şimdi hesap şöyle: miktar = risk tutarı / (stop mesafesi + giriş fiyatı × %0,35). Ayarlar yeniden seçilmeden, aynı test dönemi bir kez daha çalıştırıldı:

| 4h, test dönemi | Getiri % | Maks. düşüş % (en kötü) | Kâr faktörü | Sharpe |
|---|---|---|---|---|
| maliyet hesaba katılmadan | +4,30 | 6,48 (9,44) | 1,60 | 0,42 |
| maliyet hesaba katılarak | +4,29 | 6,13 (8,93) | 1,62 | 0,44 |

Etkisi küçük, çünkü pozisyonlar çoğu zaman %25 maruziyet sınırına takılıyor. Düşüşler biraz azaldı, getiri neredeyse aynı kaldı. Bu raporun diğer tablolarındaki "yeni" rakamlar maliyet dahil boyutlandırmayla hesaplandı.

**Yeni, varsayılan olarak kapalı ayarlar** (panelden canlı açılabilir):

- `ema_slope_bars`: trend EMA'sının son N mumda yükselmesini şart koşar.
- `adx_min`: giriş için en düşük ADX (trend gücü).
- `min_atr_pct`: çok sakin piyasayı atlar.

Geliştirme döneminde tek başına veya yeni ayarlarla birlikte sonucu belirgin biçimde iyileştirmedikleri için kapalı bırakıldılar.

**Migration.** Veritabanı şeması değişmedi, ama `state_manager` **migration 2** eklendi. Bu migration, `rsi_long_max`, `atr_sl_multiplier`, `risk_reward_ratio` ve `trailing_atr_multiplier` hâlâ eski varsayılan değerindeyse onları yeni değere çeker. Elle değiştirdiğiniz değerlere dokunmaz. Risk yüzdesi, zarar limiti, maruziyet ve mod ayarlarına hiç dokunmaz. Bot, masaüstü ya da telefon uygulaması bir sonraki açılışta bunu kendiliğinden yapar.

## Güvenilirlik kontrolleri

Bu kontroller, ayarlar seçildikten sonra yapıldı. Sonuçlara göre hiçbir ayar değiştirilmedi.

### 1. Ayarlamada hiç kullanılmayan 9 parite (4 saat)

ADA, DOGE, AVAX, LINK, DOT, LTC, TRX, ATOM ve NEAR (USDT paritelerinde) ayar seçimine hiç katılmadı. Yeni varsayılanlar bu paritelerde değiştirilmeden, aynı maliyetlerle ve Ocak 2021 ile Ağustos 2026 arasında çalıştırıldı.

| Parite | İşlem | Kazanma % | Kâr faktörü | Getiri % (tüm dönem) | Maks. düşüş % | Getiri % (Tem 2024 sonrası) | Al-ve-tut % (tüm dönem) | Al-ve-tut % (Tem 2024 sonrası) |
|---|---|---|---|---|---|---|---|---|
| ADA | 46 | 41,3 | 1,97 | +20,12 | 8,33 | -2,80 | +8 | -51 |
| DOGE | 46 | 39,1 | 2,16 | +27,86 | 10,39 | +14,41 | +1564 | -35 |
| AVAX | 48 | 33,3 | 1,63 | +16,26 | 11,11 | -8,23 | +133 | -76 |
| LINK | 54 | 25,9 | 1,20 | +5,82 | 12,67 | +9,89 | -2 | -21 |
| DOT | 39 | 33,3 | 0,98 | -0,29 | 8,16 | -1,09 | -91 | -87 |
| LTC | 50 | 30,0 | 0,82 | -5,07 | 15,52 | -6,61 | -63 | -36 |
| TRX | 46 | 41,3 | 2,32 | +25,13 | 8,76 | +4,10 | +1125 | +166 |
| ATOM | 49 | 10,2 | 0,81 | -5,84 | 16,55 | -7,86 | -76 | -78 |
| NEAR | 49 | 28,6 | 1,38 | +10,58 | 13,69 | +3,64 | +33 | -64 |

Ortalamalar ve eski ayarlarla karşılaştırma:

| 9 yeni parite, 4h | Dönem | Getiri % | Maks. düşüş % | Kâr faktörü | Sharpe | Kârlı |
|---|---|---|---|---|---|---|
| eski ayarlar | tüm dönem | -1,35 | 7,08 | 0,96 | -0,07 | 4/9 |
| **yeni ayarlar** | tüm dönem | **+10,51** | 11,69 | 1,47 | **0,33** | **6/9** |
| eski ayarlar | Tem 2024 sonrası | -1,15 | 4,65 | 1,43 | -0,25 | 4/9 |
| **yeni ayarlar** | Tem 2024 sonrası | **+0,61** | 7,92 | 1,13 | **-0,12** | 4/9 |

Aynı pariteler 1 saatlik grafikte yeni ayarlarla tüm dönemde ortalama -%9,4 kaybettirdi (eski ayarlar: -%14,4).

**Sonuç:** Yeni ayarlar tanımadıkları paritelerde de eski ayarlardan iyi. Tüm dönemde 9 paritenin 6'sı kârda, ama kazanç ilk 5 paritedekinden belirgin biçimde düşük. Son iki yılda bu paritelerde sonuç **başa baş**: ortalama +%0,6 ve 9 paritenin 4'ü kârda. Bu dönemde bu altcoinlerin çoğu %35 ile %87 arasında değer kaybetti; bot bu düşüşlerin çok azına maruz kaldı. Kısacası strateji düşen piyasada sermayeyi korudu, ama bu dönemde kazandırmadı. Yıl yıl bakınca yeni ayarlar 2021, 2023 ve 2024'te kârda, 2022 ve 2025'te küçük zararda (-%1,7 ve -%1,8).

### 2. Hassasiyet testi (ayarı bir adım oynatınca ne oluyor)

Ayarlanan her değer bir adım aşağı ve yukarı oynatıldı. Diğer ayarlar sabit tutuldu; 5 ana parite, 4 saat.

| Değişiklik | Tüm dönem getiri % | Tüm dönem Sharpe | Tem 2024 sonrası getiri % | Tem 2024 sonrası Sharpe | Kârlı (Tem 2024 sonrası) |
|---|---|---|---|---|---|
| **varsayılan** | +23,51 | 0,72 | +4,29 | 0,44 | 5/5 |
| stop 2,5 ATR | +24,87 | 0,65 | +3,83 | 0,36 | 4/5 |
| stop 3,5 ATR | +22,61 | 0,75 | +4,68 | 0,51 | 4/5 |
| trailing 4 ATR | +21,44 | 0,69 | +3,21 | 0,34 | 3/5 |
| trailing 6 ATR | +23,09 | 0,66 | +3,48 | 0,36 | 5/5 |
| hedef 5R | +17,99 | 0,60 | +2,02 | 0,24 | 3/5 |
| hedef 20R | +28,36 | 0,76 | +6,57 | 0,52 | 5/5 |
| RSI üst sınırı 80 | +21,77 | 0,67 | +4,65 | 0,48 | 5/5 |
| RSI üst sınırı 90 | +22,95 | 0,71 | +4,29 | 0,44 | 5/5 |
| RSI alt sınırı 40 veya 50 | +23,51 | 0,72 | +4,29 | 0,44 | 5/5 |

**Sonuç:**

- **4 saatlik grafikte sonuç, ayarlar oynatılınca çökmüyor.** Bütün komşu ayarlar kârda kalıyor ve Sharpe 0,24 ile 0,52 arasında değişiyor. Bu, rastgele bulunmuş sivri bir tepe olmadığını gösteriyor; seçilen değerler geniş bir "iyi bölgenin" içinde.
- Kâr hedefi yaklaştıkça (5R) sonuç zayıflıyor. Kazançları trailing stopun bırakması önemli.
- **RSI alt sınırının hiçbir etkisi yok.** Kırılım olan mumlarda RSI zaten 50'nin üstünde. Yani momentum katmanı şu an pratikte bir şey filtrelemiyor ve sinyali trend, MACD+hacim ve kırılım katmanları belirliyor. Bu bir hata değil, ama çok katmanlı yapının bir katmanının şu an işlevsiz olduğunu bilmek gerekiyor.
- **1 saatlik grafikte sonuç kırılgan.** Stop 3 yerine 2,5 ATR olunca tüm dönem sonucu sıfırın altına düşüyor (-%0,8), trailing 4 ATR olunca yarıya iniyor. 1 saatlik grafik için bu ayarlara güvenilmemeli.

### 3. Walk-forward testi (kayan pencereler)

_Eklendi: 28 Eylül 2026._

İki soru soruldu. Şu anki varsayılanlar dönem dönem ayakta kalıyor mu? Ayarları her 6 ayda bir yeniden seçmek (yeniden ayarlama), sabit ayarlardan daha iyi mi?

**Nasıl yapıldı (`scripts/walk_forward.py`).**

- 14 parite (5 ana ve 9 ek parite), 4 saatlik mumlar, Ocak 2021 ile Ağustos 2026 arası. Maliyetler öncekiyle aynı.
- Her pencerede 24 aylık bir **ayarlama dönemi** ve hemen arkasından 6 aylık bir **test dönemi** var. Pencere her seferinde 6 ay kayıyor. Böylece Ocak 2023 ile Ağustos 2026 arasında 8 test penceresi çıkıyor; sonuncusu 2 ay.
- Her pencerede üç ayar karşılaştırıldı:
  - **Sabit:** botun şu anki varsayılanları, hiç değiştirilmeden.
  - **Yeniden ayarlama:** 160 ayar kombinasyonu (stop 2 ile 4 ATR, trailing 3 ile 6 ATR, hedef 3R ile 20R, RSI üst sınırı 70 ya da yok) ayarlama döneminde denendi. 14 paritede ortalama Sharpe'ı en yüksek olan seçildi ve test döneminde çalıştırıldı. Test dönemini hiç görmedi.
  - **Eski varsayılanlar** (2:1), karşılaştırma için.
- Her parite için test pencereleri uç uca eklenip tek bir test eğrisi yapıldı.
- **Karar kuralı, test çalıştırılmadan önce yazıldı** (koddaki `decide`). Yeniden ayarlama varsayılanların yerine ancak şu üç şartın hepsini sağlarsa geçecekti. Bu şartlar hem tüm pencerelerde hem de Temmuz 2024 sonrası pencerelerde aranacaktı:
  1. birleşik test Sharpe'ı daha yüksek,
  2. pencerelerin yarısından fazlasında sabit ayarları geçiyor,
  3. en kötü düşüşü 2 puandan fazla kötüleşmiyor.

**Uyarı:** Sabit varsayılanlar Ocak 2021 ile Haziran 2024 arasındaki veriye bakılarak seçildi. Bu yüzden Temmuz 2024 öncesindeki 3 pencerede sabit ayarlar avantajlı, çünkü o dönemi görmüşlerdi. Adil karşılaştırma, Temmuz 2024 sonrasındaki 5 pencere.

**Pencere pencere sonuçlar.** Değerler 14 paritenin ortalaması: getiri % / Sharpe / kârlı parite sayısı.

| Test dönemi | Sabit (şu anki) | Yeniden ayarlama | Eski varsayılanlar | Al-ve-tut % | O pencerede seçilen ayar |
|---|---|---|---|---|---|
| 2023 1. yarı \* | +1,6 / 0,43 / 8 | +2,0 / 0,80 / 11 | -1,2 / -1,13 / 2 | +32 | stop 3,5 · trailing 6 · hedef 5R |
| 2023 2. yarı \* | +3,2 / 0,75 / 10 | +3,5 / 1,08 / 10 | +0,1 / -0,29 / 5 | +92 | stop 4 · trailing 6 · hedef 5R |
| 2024 1. yarı \* | +0,3 / -0,04 / 6 | +0,1 / -0,15 / 8 | +0,8 / 0,34 / 9 | +14 | stop 4 · trailing 6 · hedef 5R |
| 2024 2. yarı | +2,0 / 0,41 / 11 | +2,5 / 0,40 / 11 | -0,4 / -0,21 / 6 | +63 | stop 3,5 · trailing 6 · hedef 20R |
| 2025 1. yarı | -0,9 / -1,05 / 2 | -1,0 / -1,13 / 2 | -0,8 / -1,23 / 2 | -25 | stop 3,5 · trailing 6 · hedef 20R |
| 2025 2. yarı | +0,6 / 0,00 / 7 | +0,4 / -0,15 / 7 | +0,2 / 0,17 / 7 | -18 | stop 3,5 · trailing 6 · hedef 20R |
| 2026 1. yarı | -1,3 / -1,19 / 3 | -1,0 / -1,18 / 4 | -1,2 / -1,73 / 2 | -34 | stop 2 · trailing 6 · hedef 10R · RSI ≤ 70 |
| 2026 Temmuz-Ağustos | +1,7 / 0,06 / 5 | +1,3 / 0,35 / 3 | +0,1 / -0,20 / 3 | +22 | stop 3 · trailing 4 · hedef 10R · RSI ≤ 70 |

_\* Sabit ayarlar bu dönemi ayarlama sırasında görmüştü. "RSI ≤ 70" yazmayan satırlarda RSI üst sınırı yok._

**Test pencereleri uç uca eklenince** (14 paritenin ortalaması):

| Dönem | Ayar | Getiri % | Ort. maks. düşüş % | En kötü maks. düşüş % | Sharpe | Kârlı |
|---|---|---|---|---|---|---|
| Ocak 2023 - Ağustos 2026 | **sabit (şu anki)** | **+7,3** | 9,2 | 16,0 (ATOM) | **0,35** | **10/14** |
| | yeniden ayarlama | +7,6 | 8,0 | 14,7 (ATOM) | 0,40 | 12/14 |
| | eski varsayılanlar | -2,4 | 6,0 | 11,4 | -0,33 | 3/14 |
| | al-ve-tut | +167 (ortanca +78) | | | | 9/14 |
| Temmuz 2024 - Ağustos 2026 | **sabit (şu anki)** | **+2,0** | 7,3 | 9,8 | **0,08** | **9/14** |
| | yeniden ayarlama | +2,0 | 6,6 | 10,1 | 0,07 | 9/14 |
| | eski varsayılanlar | -2,0 | 4,6 | 9,1 | -0,45 | 4/14 |
| | al-ve-tut | -7 (ortanca -32) | | | | 4/14 |

**Karar: varsayılanlar değişmedi.** Yeniden ayarlama tüm dönemde 8 pencerenin 4'ünde, Temmuz 2024 sonrasında 5 pencerenin 2'sinde sabit ayarları geçti. Temmuz 2024 sonrasında birleşik Sharpe neredeyse aynı (0,07 ve 0,08). Kural iki dönemde de "yarıdan fazla pencerede kazanma" şartını sağlamadı. Yani ayarları her 6 ayda yeniden seçmek, sabit ayarlardan daha iyi sonuç vermiyor.

**Kontrol: 12 aylık ayarlama dönemi.** Aynı test 12 aylık ayarlama dönemiyle de çalıştırıldı (10 test penceresi, Ocak 2022'den başlıyor). Yeniden ayarlama burada daha kötü çıktı: tüm dönemde Sharpe 0,13, sabit ayarlarda 0,23. Seçilen ayarlar da pencereden pencereye daha çok değişti (stop 2 ile 4 ATR, trailing 3 ile 6 ATR, hedef 3R ile 20R arası). Kısa geçmişe göre ayar seçmek gürültüye uymak demek.

**Ne öğrendik:**

- **Şu anki ayarlar, ayarlanırken hiç görülmeyen dönemde küçük ama pozitif kaldı.** Temmuz 2024 sonrasında 14 paritede ortalama +%2,0, 9 parite kârda, Sharpe 0,08. Bu, önceki test döneminde 5 ana paritede görülen +%4,3'ten zayıf. Üstünlük küçük.
- **Düşen piyasada sermayeyi koruyor.** 2025 ve 2026'nın ilk yarısında al-ve-tut -%18 ile -%34 kaybederken strateji -%0,9 ile -%1,3 arasında küçük zarar etti. Temmuz 2024 sonrasında 14 paritede al-ve-tut ortalama -%7 iken strateji +%2. Ama Ocak 2023'ten beri bakınca al-ve-tut çok önde: +%167 ve +%7.
- **Ayarlar geniş bir iyi bölgenin içinde.** 24 aylık ayarlama 8 pencerenin 7'sinde trailing 6 ATR seçti, stop da çoğunlukla 3,5 ile 4 ATR arasında kaldı. Şu anki ayarlar (stop 3, trailing 5) bu bölgeye yakın. Buna rağmen bu değerlere geçmek test döneminde bir kazanç getirmedi.
- **Son dönemde hiçbir ayar güçlü değil.** Ayarlama döneminde bulunan en iyi Sharpe ilk 6 pencerede 0,43 ile 0,74 arasındaydı, son iki pencerede 0,19'a ve -0,01'e düştü. Son iki yılda bu strateji için piyasa zor geçti.
- **Eski varsayılanlar (2:1) yine en kötüsü.** 14 paritenin 11'inde zararda.
- **Otomatik fren backtest'te yok.** En kötü birleşik düşüş %16 (ATOM, 2023 ile 2026 arası). Gerçek botta %15'lik düşüş freni burada yeni işlemleri durdururdu.

Bu test her pazartesi "Real-data backtest" iş akışında 5 ana paritede yeni veriyle tekrar çalışır. Sonuç, çalışmanın özet sayfasında ve `backtest-data` dalındaki `results/walk-forward` klasöründe durur.

## Paper modda ne beklemeli

Bu rakamlar, yeni varsayılanların 4 saatlik grafikte 14 paritedeki (5 ana ve 9 ek parite; Ocak 2021 ile Ağustos 2026 arası) backtest işlemlerinden alındı. Toplam 695 işlem var. Paper sonuçlarını bunlarla karşılaştır. Aşağıdaki aralıklarda kaldığı sürece bot beklendiği gibi çalışıyor demektir.

| Ölçü | Tipik (ortanca) | Aralık / en kötü |
|---|---|---|
| Parite başına ayda işlem | 0,7 | 0,6 ile 0,9 arası |
| Kazanma oranı | %32 | %10 ile %41 arası |
| Ortalama kazanç | +2,7R | 1,5R ile 4,8R arası |
| Ortalama kayıp | -0,7R | -0,6R ile -0,8R arası |
| Arka arkaya kaybeden işlem (en uzun seri) | 7-8 | 13 (ATOM) |
| Bir işlemin süresi | ~6 gün | 4,5 ile 7,7 gün arası |
| Bir yıl içindeki en büyük düşüş | %4 | %10 |
| Tüm dönemdeki en büyük düşüş | %11 | %17 |

_R, işleme girerken planlanan risk tutarıdır. Varsayılanlarla bu, bakiyenin en fazla %1'i._

Bu tablo pratikte şu anlama geliyor:

- **İşlem az olacak.** Varsayılan iki pariteyle (BTC ve ETH) ayda toplam 1-2 işlem bekle. Hiç işlem olmayan haftalar normal.
- **Çoğu işlem küçük zararla kapanacak.** Her 3 işlemden yaklaşık 2'si kaybeder. Kârı, arada bir gelen büyük kazançlar getirir: işlemlerin yaklaşık %10'u 3R'nin üstünde kazanır, en büyüğü 9,7R. Bu yüzden 6 ay sonunda toplam sonuç, hangi büyük hareketlerin yakalandığına çok bağlı olacak.
- **Arka arkaya 7-8 kaybeden işlem normal.** Bu kadar seri, bakiyeyi yaklaşık %4-6 düşürür ve backtest'te her paritede görüldü. 13 kayıplık bir seri bile yaşandı. Bu tek başına botun bozulduğunu göstermez.
- **Ne zaman endişelenmeli:**
  - kayıplar düzenli olarak -1R'den büyükse (stop dolumları beklenenden kötü demektir),
  - ayda parite başına 2'den fazla işlem açılıyorsa (ayarlar veya zaman dilimi değişmiş olabilir),
  - düşüş %15'i geçiyorsa (backtest'teki en kötü değerin yakını),
  - 15 işlemden fazla kazanç gelmiyorsa.

  Bu durumlarda botu durdurup kayıtlara bak.
- 6 ay paper modda iki pariteyle yaklaşık 10 işlem çıkar. Bu, sonucu kesin olarak yorumlamak için az. Rakamlar bu tablonun aralığındaysa bot doğru çalışıyor demektir, ama kârlı olacağı kanıtlanmış olmaz.

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
- **Tanımadığı paritelerde son iki yıl başa baş.** Yukarıdaki güvenilirlik kontrolüne göre üstünlük, ayarların seçildiği 5 paritede görünenden daha küçük.

## Öneriler

1. **4 saatlik grafikte en az 6 ay paper modda çalıştırın.** Bu ayarlarla parite başına ayda ortalama 1 işlem bile çıkmaz. Sabırlı olun; sonuçları "Paper modda ne beklemeli" bölümündeki aralıklarla karşılaştırın.
2. **15 dakika ve altını kullanmayın.** Maliyetler her ayarda kazancı aşıyor.
3. **Canlıya geçerseniz küçük başlayın ve BNB ile komisyon indirimi kullanın.** Maliyet bu stratejinin en büyük düşmanı.
4. **Denemeye değer fikirler (paper modda):**
   - Düşüş piyasalarında daha az işlem için `ema_slope_bars=50` deneyebilirsiniz. Geliştirme döneminde 2022 kaybını azalttı, ama genel sonucu iyileştirmedi.
   - Portföy düzeyinde bir test (aynı bakiyeyle birden çok parite) yapılabilir. Bu henüz yapılmadı.
5. **Her hafta yeni veriyle kontrol edin.** GitHub Actions'daki "Real-data backtest" iş akışı her pazartesi yeni ay verisiyle tekrar çalışır; elle de başlatılabilir. Walk-forward testi de bu çalışmanın içinde. Sonuçlar çalışmanın özet sayfasında ve `backtest-data` dalında durur.
6. **Ayarları sık sık yeniden seçmeyin.** Walk-forward testine göre son 1-2 yılın en iyi ayarına geçmek, sabit ayarlardan daha iyi sonuç vermedi.

## Kendiniz çalıştırmak için

```bash
python scripts/download_history.py --timeframes 1h,4h --start 2021-01           # data/history/ klasörüne indirir
python scripts/backtest_matrix.py --data data/history --split 2024-07-01 --yearly \
    --variant "eski:atr_sl_multiplier=1.5,risk_reward_ratio=2,trailing_atr_multiplier=2,rsi_long_max=70"
python scripts/walk_forward.py --data data/history --timeframe 4h                # kayan pencere testi
python backtest.py --csv data/history/BTCUSDT-4h.csv.gz --trades-csv islemler.csv
```

> ⚠️ **Bu bot kâr garantisi vermez, yatırım tavsiyesi değildir.** Geçmiş performans (backtest dahil) gelecekteki sonuçları göstermez. Canlıya geçmeden önce uzun süre paper trading ve mümkünse testnet ile doğrulayın. Kaybetmeyi göze alamayacağınız parayla işlem yapmayın.
