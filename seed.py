"""
Portföyü tek seferde yükleyen script.
Çalıştırmak için Railway terminalinde:
    railway run python seed.py
Ya da lokal olarak (aynı klasörde):
    python seed.py
"""
import os
from database import init_db, add_holding

# ── Telegram OWNER_ID'ni buraya yaz ──────────────────────────
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
if OWNER_ID == 0:
    raise SystemExit("❌ OWNER_ID ortam değişkeni ayarlanmamış. Railway'de Variables kısmına bak.")

# ── Portföy verileri (ekrandan alındı) ───────────────────────
HOLDINGS = [
    # (ticker,   adet,    ortalama_maliyet)
    ("AAGYO",    145,     21.10),
    ("AKBNK",    38,      77.21),
    ("ALVES",    1415,    3.32),
    ("CIMSA",    44,      48.79),
    ("EKGYO",    324,     21.39),
    ("GARAN",    30,      133.31),
    ("GRSEL",    16,      310.28),
    ("SELEC",    144,     80.53),
    ("YKBNK",    77,      38.50),
    ("NSP",      50324,   1.442022),
]

init_db()

for ticker, qty, cost in HOLDINGS:
    add_holding(OWNER_ID, ticker, qty, cost)
    print(f"✅ {ticker}: {qty:,.0f} adet @ {cost} ₺")

print(f"\n🎉 {len(HOLDINGS)} pozisyon başarıyla yüklendi!")
