# Universal Host Manager — macOS uygulaması

Durum: İlk mimari taslak. Bu klasör, mevcut MCP sunucusundan ayrı bir çalışma alanıdır.

## Hedef

Mac kullanıcısı kurulum sihirbazında kullanacağı özellikleri seçsin, macOS izinlerini gerçek uygulama üzerinden sınasın ve menü çubuğundaki kontrol panelinden MCP bağlantısını yönetebilsin. İlk kurulum terminal bilgisi gerektirmesin.

## İlk sürüm sınırı

1. Yerel mod: kullanıcı çalışma klasörünü ve etkin araç gruplarını seçer.
2. Uygulama, arka plandaki MCP sunucusunu başlatır/durdurur ve sağlık durumunu gösterir.
3. Seçilen özellikler için gerçek erişim denemesi yapılır; gerektiğinde kullanıcı macOS ayarlarına yönlendirilir.
4. Kontrol panelinde çalışma durumu, etkin özellikler ve kısa işlem geçmişi görünür.
5. Uzak erişim, Auth0, ngrok ve Cloudflare entegrasyonu sonraki aşamada değerlendirilir.

## Önerilen bileşenler

- SwiftUI: kurulum sihirbazı, menü çubuğu ve kontrol paneli.
- Arka plan yardımcısı: sunucunun yaşam döngüsü ve sağlık kontrolü.
- MCP çekirdeği: mevcut Universal Host Manager MCP koduyla paylaşılacak sunucu ve araçlar.
- Yerel yapılandırma: özellik seçimi ve çalışma klasörü; sırlar için macOS Keychain.
- Yetki katmanı: seçili olmayan araçları sunucu tarafında engeller ve erişim denemelerini kaydeder.

## Temel güvenlik kararı

Sınırsız shell açıksa diğer özelliklerin kapatılması güvenilir bir sınır oluşturmaz. Bu nedenle ilk sürümde sınırsız shell varsayılan olarak kapalı olmalı; gerekiyorsa ayrı ve açıkça belirtilen bir ileri düzey yetki olarak sunulmalı. Dosya erişimi seçilen klasörle sınırlandırılmalı. macOS gizlilik izinleri kullanıcı tarafından verilir; sihirbaz bunları kendisi onaylayamaz. İzin testi Terminal üzerinde değil, kurulacak uygulamanın gerçek çalışma süreci üzerinde yapılmalı.

## Henüz kararlaştırılacak konular

- İlk hedef: yalnızca Ahmet'in Mac'i için prototip mi, genel kullanıma açılacak ürün mü?
- Python sunucusu uygulamaya paketlenecek mi; hangi macOS sürümleri desteklenecek?
- Shell için ayrı onay/komut izin listesi gerekiyor mu?
- Kontrol panelinde bağlantı geçmişi ve işlem kaydı nasıl gösterilecek?
- Mevcut Python deposuyla ortak kod, sürümleme ve dağıtım stratejisi.

## İlk somut adım

Kurulum akışının ekranlarını ve her ekrandaki seçeneklerin sunucuda hangi ayara dönüştüğünü tanımla. Ardından yerel modda en küçük çalışan prototipi hazırla.
