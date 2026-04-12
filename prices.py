import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# TEFAS'tan çekilecek fon kodları (buraya ekleyebilirsiniz)
TEFAS_FUNDS = {"NSP", "TTE", "MAC", "GAF", "IEF"}  # örnek liste, dilediğiniz kodu ekleyin


# ─────────────────────────────────────────────
#  TEFAS fon fiyatı
# ─────────────────────────────────────────────
def _fetch_tefas(fund_code: str) -> float | None:
    """TEFAS API'sinden fon birim pay değerini çek."""
    today = datetime.now().strftime("%d.%m.%Y")
    week_ago = (datetime.now() - timedelta(days=10)).strftime("%d.%m.%Y")

    url = "https://www.tefas.gov.tr/api/DB/BindHistoryInfo"
    params = {
        "fontip": "YAT",
        "sfonkod": fund_code.upper(),
        "bastarih": week_ago,
        "bittarih": today,
        "islemtipi": "I",
    }
    tefas_headers = {
        **HEADERS,
        "Referer": "https://www.tefas.gov.tr/FonAnaliz.aspx",
        "Origin": "https://www.tefas.gov.tr",
    }
    try:
        r = requests.get(url, params=params, headers=tefas_headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data", [])
        if not rows:
            logger.warning(f"TEFAS veri yok: {fund_code}")
            return None
        # Son güne ait fiyat
        last = rows[-1]
        raw = last.get("BirimPayDegeri") or last.get("FIYAT") or last.get("fiyat")
        if raw is not None:
            return round(float(str(raw).replace(",", ".")), 6)
    except Exception as e:
        logger.debug(f"TEFAS hatası ({fund_code}): {e}")
    return None


# ─────────────────────────────────────────────
#  Yahoo Finance hisse fiyatı
# ─────────────────────────────────────────────
def _fetch_yahoo(symbol: str) -> float | None:
    """Yahoo Finance API'sine direkt istek at."""
    for base in ["query1", "query2"]:
        url = f"https://{base}.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.raise_for_status()
            data = r.json()
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if closes:
                return round(closes[-1], 4)
        except Exception as e:
            logger.debug(f"Yahoo ({base}) başarısız ({symbol}): {e}")
    return None


# ─────────────────────────────────────────────
#  Tek fiyat çek
# ─────────────────────────────────────────────
def get_price(ticker: str) -> float | None:
    """
    Fiyat kaynağını otomatik seç:
    - TEFAS_FUNDS listesindeyse → TEFAS
    - Değilse → Yahoo Finance (.IS)
    """
    t = ticker.upper()

    if t in TEFAS_FUNDS:
        price = _fetch_tefas(t)
        if price is None:
            logger.warning(f"TEFAS fiyat alınamadı: {t}")
        return price

    # Önce Yahoo dene, bulamazsa TEFAS'ta ara (bilinmeyen fon olabilir)
    price = _fetch_yahoo(f"{t}.IS")
    if price is not None:
        return price

    # Yahoo'da yoksa TEFAS'ta dene (kullanıcı fon kodunu eklemiş olabilir)
    price = _fetch_tefas(t)
    if price is not None:
        logger.info(f"{t} TEFAS'ta bulundu, TEFAS_FUNDS listesine eklemeniz önerilir.")
    return price


# ─────────────────────────────────────────────
#  Toplu fiyat çek
# ─────────────────────────────────────────────
def get_prices_bulk(tickers: list[str]) -> dict[str, float | None]:
    """Birden fazla ticker için fiyat çek: {ticker: price}"""
    return {ticker: get_price(ticker) for ticker in tickers}
