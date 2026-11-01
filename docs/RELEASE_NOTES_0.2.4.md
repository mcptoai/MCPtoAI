# MCPtoAI 0.2.4 — Sürüm notları

## Windows eşleştirme

- Bilgisayarın yerel dil ayarı Türkçe olmasa da Windows Desktop üzerinden cihaz eşleştirmesi artık çalışır.
- Eşleştirme sırasında hata oluşursa daha açıklayıcı hata bilgisi gösterilir. Giriş bağlantısı alınmışsa bağlantıyı tarayıcıda açma veya kopyalama seçeneği sunulur.

## Masaüstü uygulaması

- Uygulamanın ikinci kez açılması mevcut pencereyi öne getirir; gereksiz ikinci pencere açılmaz.
- Uygulama simgesinin paket içinde eksik kalmasına neden olabilen sorun giderildi.

## Linux ve komut satırı

- Linux komut satırı girişinde ve Windows Device Agent başlatılırken terminal çıktısı kodlaması daha güvenilir hale getirildi.

## Bilinen sınırlar

- Terminal komutları ve harici MCP araçları **işletim sistemi düzeyinde sandbox içinde değildir**. Onay ekranları önemlidir; komutlar kullanıcı hesabının erişebildiği kaynaklara erişebilir.
- Keynote `.key` dosyaları, özel anahtarlarla aynı uzantıyı taşıdığı için engellenir.
- Linux wheel paketi **imzasızdır**. İndirdiğiniz paketin yayınlanan **SHA-256/SHA-512** sağlama toplamlarını güvenilir yayın kaynağıyla karşılaştırın. Bu kontroller dijital imzanın yerini tutmaz.
- Hassas dosya koruması, kullanıcının yetkileriyle çalışan keyfî terminal komutları için bir işletim sistemi güvenlik sınırı değildir.
- Uzun süren sohbetler, uygulama veya Agent güncellemesi sırasında kısa süreli bağlantı kesintisi yaşayabilir.

## Yükseltme

- Platformunuza uygun MCPtoAI Desktop paketini güvenilir resmî dağıtım kaynağından edinin; Windows'ta kurulum dosyasını, macOS'ta uygun uygulama paketini kullanın.
- Mevcut cihaz eşleştirmesini ve kaydedilmiş API anahtarlarını koruyun; sırları yeni bir ortama taşımadan önce yedekleme ve erişim yetkilerinizi kontrol edin.
- Linux komut satırı kullanıcıları, kullandıkları paket yöneticisiyle `mcptoai` paketini güncelleyebilir. İndirilen wheel'in sağlama toplamını doğrulayın.
