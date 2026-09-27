# Trading Bot Desktop

Botu bilgisayardan izlemek için Electron + React + TypeScript uygulaması. Botun HTTP API'sine
bağlanır (API `api/` klasöründe ayrı geliştiriliyor). Uygulama **emir açmaz ve paper/canlı modu
değiştiremez**. Yapabildiği yalnızca iki yazma işlemi var:

- Bir pozisyon için kapatma komutunu botun komut kuyruğuna eklemek (`POST /api/positions/{id}/close`).
  Emri bot kendi döngüsünde gönderir.
- Strateji/risk ayarlarını güncellemek (`PUT /api/settings/{key}`). Adında `mode`, `paper`, `live`,
  `api_key` veya `secret` geçen anahtarları uygulama reddeder.

## Ekranlar

- **Durum çubuğu:** paper/canlı, bot çalışıyor mu, günlük zarar limiti yüzünden girişler durdu mu,
  borsa, semboller, bugünkü PnL, anlık akış bağlantısı.
- **Genel bakış:** mum grafiği (giriş, stop, kâr al ve trailing çizgileriyle), performans özeti,
  açık pozisyonlar ve onaylı "Kapat" butonu.
- **İşlem geçmişi**, **Strateji ayarları** (canlı düzenleme), **Loglar** (filtreli terminal),
  **Bağlantı** (API adresi ve token).

## Kurulum

Node.js 20 veya üstü gerekir.

```bash
cd desktop
npm install
```

## Geliştirme (mock API ile)

Gerçek bot olmadan çalışmak için sahte bir API sunucusu var:

```bash
npm run mock      # http://127.0.0.1:8765, token: dev-token
npm run dev       # ayrı bir terminalde: Vite + Electron
```

Uygulamada **Bağlantı** sekmesine adres olarak `http://127.0.0.1:8765`, token olarak `dev-token`
girin. İlk açılışta `TRADINGBOT_API_URL` ve `TRADINGBOT_API_TOKEN` ortam değişkenleri de okunur.

## Gerçek bota bağlanma

Botun API sunucusunu başlatın (varsayılan `http://127.0.0.1:8000`) ve `.env` içindeki `API_TOKEN`
değerini **Bağlantı** sekmesine girin. Token, işletim sisteminin anahtar deposuyla (Electron
`safeStorage`) şifrelenip kullanıcı klasöründe saklanır ve arayüz tarafına hiç geçmez. Tüm istekler
Electron ana sürecinden gider, bu yüzden API'de CORS ayarı gerekmez.

## Komutlar

| Komut | Ne yapar |
| --- | --- |
| `npm run dev` | Geliştirme modunda açar |
| `npm run mock` | Sahte API sunucusunu başlatır |
| `npm run typecheck` | TypeScript kontrolü |
| `npm test` | İzin verilen çağrılar ve mock API'ye karşı istemci testleri |
| `npm run build` | `dist/` ve `dist-electron/` üretir |
| `npm start` | Derlenmiş uygulamayı açar |
| `npm run dist` | electron-builder ile kurulum paketi (Windows: NSIS, macOS: dmg, Linux: AppImage) |

## Yapı

```
desktop/
  electron/    ana süreç: API istemcisi, izin verilen çağrılar, WebSocket, token saklama, preload
  shared/      API sözleşmesi tipleri (ileride mobil uygulamayla paylaşılabilir)
  src/         React arayüzü
  mock/        geliştirme için sahte API
  tests/       node:test testleri
```

Bu uygulama bir izleme aracıdır; kâr garantisi vermez ve yatırım tavsiyesi değildir.
