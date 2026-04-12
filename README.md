# 📊 BIST Portföy Telegram Botu

BIST hisselerinizi takip etmek için Telegram botu. Yahoo Finance üzerinden anlık fiyat çeker, kar/zarar durumunuzu gösterir.

---

## 🤖 Bot Komutları

| Komut | Açıklama |
|-------|----------|
| `/start` veya `/yardim` | Yardım menüsü |
| `/ekle` | Adım adım hisse ekle |
| `/portfoy` | Portföy durumunu göster |
| `!portföy` | Grup sohbetlerinde portföy göster |
| `/liste` | Hisseleri listele |
| `/sil GARAN` | Belirli hisseyi sil |
| `/temizle` | Tüm portföyü temizle |
| `/iptal` | Aktif işlemi iptal et |

---

## 🚀 Kurulum

### 1. Telegram Bot Token Al

1. Telegram'da [@BotFather](https://t.me/BotFather) ile konuş
2. `/newbot` yaz ve talimatları takip et
3. Sana verilen **token'ı** kopyala

### 2. Lokal Çalıştırma

```bash
# Gereksinimleri yükle
pip install -r requirements.txt

# Token'ı ayarla
export TELEGRAM_BOT_TOKEN="senin_token_buraya"   # Linux/Mac
set TELEGRAM_BOT_TOKEN=senin_token_buraya         # Windows CMD

# Botu başlat
python bot.py
```

---

## ☁️ Railway'e Deploy (Ücretsiz, 7/24)

### Adım 1 — GitHub'a yükle

1. [github.com](https://github.com) hesabı aç
2. Yeni bir **private** repo oluştur
3. Bu 5 dosyayı yükle:
   - `bot.py`
   - `database.py`
   - `prices.py`
   - `requirements.txt`
   - `Procfile`

### Adım 2 — Railway hesabı oluştur

1. [railway.app](https://railway.app) adresine git
2. GitHub ile giriş yap (ücretsiz)

### Adım 3 — Proje oluştur

1. **"New Project"** → **"Deploy from GitHub repo"** tıkla
2. Az önce oluşturduğun repoyu seç
3. Deploy otomatik başlar (biraz bekle)

### Adım 4 — Token ekle

1. Projen açıkken **"Variables"** sekmesine tıkla
2. **"New Variable"** ekle:
   - **Key:** `TELEGRAM_BOT_TOKEN`
   - **Value:** BotFather'dan aldığın token
3. **"Add"** tıkla — bot otomatik yeniden başlar

### Adım 5 — Worker olarak ayarla

1. **"Settings"** → **"Deploy"** sekmesine git
2. **"Start Command"** alanına yaz: `python bot.py`
3. Kaydet

✅ Bot artık 7/24 çalışıyor!

---

## 💡 İpuçları

- **Aynı hisseyi tekrar eklerseniz** bot ağırlıklı ortalama maliyet hesaplar
- **BIST hisse kodları** büyük harf olmalı (GARAN, THYAO, EREGL, vb.)
- **Borsa kapalıyken** son kapanış fiyatı gösterilir
- Her kullanıcı **kendi portföyünü** görür (kullanıcı bazlı)

---

## 📁 Dosya Yapısı

```
bist-portfoy-bot/
├── bot.py           # Ana bot dosyası
├── database.py      # SQLite veritabanı işlemleri
├── prices.py        # Yahoo Finance fiyat çekme
├── requirements.txt # Python gereksinimleri
├── Procfile         # Railway/Heroku için başlatma komutu
└── portfolio.db     # Otomatik oluşur (SQLite veritabanı)
```
