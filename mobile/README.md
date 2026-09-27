# Trading Bot mobil uygulaması

Expo (React Native, TypeScript, Expo Router) ile yazılmış, botun HTTP API'sine (`python -m api`)
bağlanan mobil uygulama. Android ve iOS'ta çalışır.

## Ekranlar

- **Özet:** paper/live modu, bot çalışıyor mu, özsermaye, bugünkü PnL, günlük zarar limiti,
  mum grafiği (açık pozisyonun giriş/SL/TP çizgileriyle) ve PnL özeti
- **Pozisyonlar:** açık pozisyonlar, trailing stop ve onaylı **Kapat** butonu
- **İşlemler:** kapanmış işlemler
- **Log:** botun karar/olay logu, kategori filtresi, canlı akış
- **Ayarlar:** strateji/risk parametrelerini canlı düzenleme (sunucu aralıkları doğrular)

Durum, pozisyonlar ve log WebSocket ile canlı güncellenir; bağlantı koparsa uygulama kendisi
yeniden bağlanır, arka plana alınınca bağlantıyı kapatır.

## Çalıştırma (geliştirme)

Node.js 20+ gerekir.

```bash
cd mobile
npm install
npx expo start
```

Telefona **Expo Go** uygulamasını kurup terminaldeki QR kodu okutun. İlk açılışta uygulama
sunucu adresini ve `API_TOKEN` değerini sorar (bkz. ana README, "Mobil uygulama ve API").
Token telefonun güvenli deposunda (Keychain / Keystore) saklanır.

## Kontroller

```bash
npx tsc --noEmit                                  # tip kontrolü (CI'da çalışır)
npx expo export --platform android --output-dir /tmp/expo-export   # paketleme kontrolü
```

## Kurulabilir sürüm

Kalıcı bir APK/IPA için [EAS Build](https://docs.expo.dev/build/introduction/) kullanın
(`npx eas-cli@latest build`). API düz HTTP olduğundan Android release derlemesinde cleartext
trafiğe izin vermek gerekir (`expo-build-properties` eklentisi, `android.usesCleartextTraffic`);
Tailscale gibi bir VPN üzerinden bağlanmanız önerilir.

## Klasör yapısı

```
src/app/            Expo Router ekranları (_layout, connect, (tabs)/...)
src/api/            API istemcisi ve tipler (api/service.py ile aynı alanlar)
src/lib/            Bağlantı (güvenli depo), canlı veri (WebSocket), biçimlendirme, tema
src/components/     Ortak UI parçaları ve mum grafiği
```

> ⚠️ Bu uygulama ve bot kâr garantisi vermez, yatırım tavsiyesi değildir.
