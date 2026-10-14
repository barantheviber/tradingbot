# Rewards bot

Microsoft Rewards puanlarını her gün kendiliğinden toplayan bot:

- **Masaüstü Bing aramaları**: sayaç dolana kadar arar.
- **Mobil Bing aramaları**: telefon gibi görünen ayrı bir tarayıcıyla arar.
- **Günlük set (Daily Set)**: panelde kartlara tıklar, anket ve klasik Bing testlerini cevaplar.
- **Diğer görevler (More activities)**: aynı şekilde kartlara tıklar.

Bot **görünmez (headless) bir tarayıcıda, kendi ayrı profiliyle** çalışır. Fareyi ve klavyeyi
kullanmaz, pencere açmaz, odağı çalmaz. Kendi Edge/Chrome'unuzla çakışmaz. İşlemci önceliğini de
düşürür. Bot çalışırken bilgisayarınızı normal şekilde kullanabilirsiniz.

> ⚠️ **Önce okuyun.** Microsoft Rewards kuralları, puanların bot ya da otomasyonla toplanmasını
> yasaklar. Microsoft bunu fark ederse hesabın Rewards'tan çıkarılmasına ve biriken puanların
> silinmesine karar verebilir. Bot rastgele beklemeler yapar, sorguları arama kutusuna yazar ve
> Bing'in hızını aşmamak için yavaşlar, ancak **bu riski hiçbir yöntem sıfırlamaz**. Yalnızca kendi
> tek hesabınızda, riski kabul ederek kullanın. Birden fazla hesapla puan toplamak (Microsoft
> bunu kişi başına tek hesapla sınırlar) bu botun kapsamı dışındadır.

## Google için neden modül yok?

Google'da Microsoft Rewards gibi "arama yap, kartlara tıkla, puan topla" türünde bir program yok:

| Program | Puan nasıl kazanılıyor | Neden otomatikleştirilmedi |
|---|---|---|
| Google Opinion Rewards | Anket cevaplamak | Anketleri botla cevaplamak anket sahtekârlığıdır. Google tutarsız cevap verenlere anket göndermeyi keser. |
| Google Play Points | Play Store'da harcama yapmak | Otomatikleştirilecek bir görev yok; puan harcamayla gelir. |
| Google Haritalar Local Guides | Yorum ve fotoğraf eklemek | Otomatik yorum, sahte yorum demektir. Google bunları siler ve hesabı kapatır. |

Bot Google'ı yalnızca **arama sorgularını bulmak için** kullanır: Bing'de günün Google Trends
konularını arar, böylece aramalar gerçek ve güncel olur. Google'ın ileride Rewards benzeri bir
programı çıkarsa yapı yeni görev eklemeye uygundur (`runner.py`).

## Kurulum (Windows)

1. [Python 3](https://www.python.org/downloads/) kurun. Kurulumda **"Add python.exe to PATH"**
   kutusunu işaretleyin.
2. `rewards_bot\kurulum.bat` dosyasına çift tıklayın. Dosya şunları yapar:
   - ayrı bir Python ortamı (`.venv-rewards`) kurar,
   - Playwright'ı kurar (bilgisayardaki Microsoft Edge kullanılır, ayrıca tarayıcı indirilmez),
   - **bir kez** giriş penceresi açar: Microsoft hesabınızla giriş yapıp **"Oturumum açık kalsın"**
     seçeneğini işaretleyin; giriş algılanınca pencere kendiliğinden kapanır,
   - günlük otomatik görevi kurar.

Bundan sonra yapmanız gereken bir şey yok. Bot şu durumlarda arka planda, pencere açmadan çalışır:

- her gün **10:00 civarında** (yoğunluk olmasın diye en fazla 90 dk rastgele gecikmeyle),
- bilgisayar o saatte kapalıysa **açıldıktan / oturum açtıktan 15 dk sonra**.

Gün içinde bir kez başarıyla tamamlandıysa o gün tekrar çalışmaz.

## Elle kullanım

Depo klasöründe (Windows'ta `python` yerine `.venv-rewards\Scripts\python` yazın):

```bash
pip install -r rewards_bot/requirements.txt
python -m rewards_bot login          # bir kez: Microsoft hesabına giriş
python -m rewards_bot run            # bugünün puanlarını şimdi topla
python -m rewards_bot run --visible  # aynısı, tarayıcı penceresini göstererek (deneme için)
python -m rewards_bot run --only desktop,mobile   # yalnızca aramalar
python -m rewards_bot status         # puan, arama sayaçları, yapılmamış görevler
python -m rewards_bot install-task   # her gün otomatik çalıştır
python -m rewards_bot uninstall-task # otomatik çalıştırmayı kaldır
```

Linux/macOS'te `install-task`, `crontab -e` ile eklenecek satırı yazdırır. Edge kurulu değilse
`python -m playwright install chromium` çalıştırıp ayarlarda `"browser": "chromium"` yapın.

Loglar `logs/rewards_bot.log` dosyasındadır. Oturum profili ve son çalıştırmanın özeti
`data/rewards/` klasöründedir. Bu klasörde Microsoft oturumunuz durduğu için **kimseyle
paylaşmayın**.

## Nasıl çalışır?

1. **Puan bilgisi.** Panelin kendi verisi (`rewards.bing.com/api/getuserinfo`) okunur: toplam puan,
   masaüstü/mobil arama sayaçları, bugünkü görevler. Bot neyin eksik olduğunu buradan bilir.
2. **Görevler.** Her yapılmamış kart paneldeki kartın kendisine tıklanarak açılır, böylece site
   görevi bir insan tıklamış gibi kaydeder. Kart bulunamazsa görevin bağlantısı açılır. Anket ve
   klasik Bing testleri (doğru cevap sayfanın verisinde olduğu için) cevaplanır.
3. **Aramalar.** Sorgular Google Trends'ten (Türkiye), Bing'in ilgili aramalarından, Wikipedia'nın
   en çok okunanlarından, bunlara ulaşılamazsa yerleşik listeden gelir; hiçbiri tekrar edilmez.
   Her sorgu Bing'in arama kutusuna yazılır ve aramalar arasında 12–30 sn beklenir. Bot sayaca bakar:
   - sayaç doluysa durur,
   - Bing aramaların yalnızca bir kısmını sayıyorsa (bazı hesaplarda 15 dakikada birkaç arama)
     her 15 dakikada 3 arama yapacak şekilde yavaşlar,
   - puan hiç artmıyorsa birkaç denemeden sonra o gün için bırakır.
4. **Mobil aramalar.** Bot aynı oturumla, Android'deki Edge gibi görünen ikinci bir tarayıcı açar.

## Ayarlar

Ayar değiştirmek için `rewards_bot/config.example.json` dosyasını `rewards_bot/config.json` adıyla
kopyalayıp düzenleyin. Yalnızca değiştirmek istediğiniz satırları bırakmanız yeterli.

| Ayar | Varsayılan | Açıklama |
|---|---|---|
| `browser` | `msedge` | `msedge`, `chrome` (bilgisayardaki) ya da `chromium` (Playwright'ın) |
| `headless` | `true` | `false` olursa tarayıcı penceresi görünür |
| `language` / `country` | `tr` / `TR` | Tarayıcı dili ve Google Trends ülkesi |
| `desktop_searches`, `mobile_searches` | `true` | Masaüstü / mobil aramalar |
| `daily_set`, `more_activities` | `true` | Günlük set / diğer görevler |
| `search_delay_seconds` | `[12, 30]` | İki arama arasındaki rastgele bekleme (sn) |
| `cooldown_minutes` | `15` | Puan artmadığında ya da yavaş modda bekleme süresi |
| `max_stalls` | `3` | Puan hiç artmayan kaç denemeden sonra o gün bırakılsın |
| `max_searches_per_run` | `60` | Platform başına en fazla arama |
| `low_priority` | `true` | İşlemci önceliğini düşür |
| `schedule_time` | `10:00` | Otomatik görevin günlük saati (`install-task`'ı yeniden çalıştırın) |
| `schedule_random_delay_minutes` | `90` | Bu saate eklenen en fazla rastgele gecikme |

## Sorun giderme

- **"Microsoft oturumu kapalı" uyarısı:** `python -m rewards_bot login` komutunu bir kez daha
  çalıştırın. Otomatik çalışmada bu durum küçük bir uyarı penceresiyle bildirilir.
- **Aramalar puan kazandırmıyor:** Bir kez `python -m rewards_bot run --visible --only desktop`
  çalıştırıp Bing'de oturumunuzun açık olduğunu görün. Görünmez modda puan gelmiyorsa
  `config.json`'da `"headless": false` deneyin. Bu durumda pencere görünür ama yine fareyi ve
  klavyeyi kullanmaz.
- **Mobil arama "bu hesapta yok" diyor:** Mobil arama puanı bazı hesap seviyelerinde ve
  ülkelerde yoktur.
- **Görev "tamamlanamadı" görünüyor:** Microsoft panelin tasarımını sık değiştirir. Kart
  bulunamayınca bot görev bağlantısını açar ama her görev buna puan vermeyebilir. `status`
  ile kalanları görebilirsiniz.
- Microsoft Rewards'ın ülkenizde açık olduğundan emin olun (rewards.bing.com açılıyor ve puan
  gösteriyor olmalı).

## Sınırlar

- Microsoft panelin yapısını sık değiştirir. Bot hem panelin verisini hem ekrandaki kartları
  kullanarak buna dayanıklı olmaya çalışır, ama ileride seçicilerin güncellenmesi gerekebilir.
  Testler yerel bir sahte Rewards/Bing sitesine karşı çalışır, gerçek hesapla değil.
- Yapılmayanlar: Bing uygulamasına özel görevler (günlük check-in, "Read to Earn"), satın alma
  isteyen punch card'lar, Xbox görevleri.
