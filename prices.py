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
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}

# TEFAS'tan çekilecek fon kodları
TEFAS_FUNDS = {"NSP", "TTE", "MAC", "GAF", "IEF"}


# ─────────────────────────────────────────────
#  TEFAS fon fiyatı
# ─────────────────────────────────────────────
def _fetch_tefas(fund_code: str) -> float | None:
    """TEFAS'tan fon birim pay değerini çek — POST ile."""
    today    = datetime.now().strftime("%d.%m.%Y")
    week_ago = (datetime.now() - timedelta(days=10)).strftime("%d.%m.%Y")
    code     = fund_code.upper()

    tefas_headers = {
        **HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": f"https://www.tefas.gov.tr/FonAnaliz.aspx?FonKod={code}",
        "Origin":  "https://www.tefas.gov.tr",
    }
    payload = {
        "fontip":    "YAT",
        "sfonkod":   code,
        "bastarih":  week_ago,
        "bittarih":  today,
        "islemtipi": "I",
    }

    # 1. Deneme — POST
    try:
        r = requests.post(
            "https://www.tefas.gov.tr/api/DB/BindHistoryInfo",
            data=payload,
            headers=tefas_headers,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        price = _parse_tefas_response(data)
        if price:
            return price
    except Exception as e:
        logger.debug(f"TEFAS POST hatası ({code}): {e}")

    # 2. Deneme — GET
    try:
        r = requests.get(
            "https://www.tefas.gov.tr/api/DB/BindHistoryInfo",
            params=payload,
            headers=tefas_headers,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        price = _parse_tefas_response(data)
        if price:
            return price
    except Exception as e:
        logger.debug(f"TEFAS GET hatası ({code}): {e}")

    # 3. Deneme — Alternatif endpoint (fundturkey)
    try:
        r = requests.get(
            f"https://fundturkey.com.tr/api/DB/BindHistoryInfo",
            params=payload,
            headers=tefas_headers,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        price = _parse_tefas_response(data)
        if price:
            return price
    except Exception as e:
        logger.debug(f"FundTurkey hatası ({code}): {e}")

    logger.warning(f"TEFAS tüm denemeler başarısız: {code}")
    return None


def _parse_tefas_response(data: dict) -> float | None:
    """TEFAS API yanıtından fiyatı çıkar."""
    rows = data.get("data", [])
    if not rows:
        return None
    last = rows[-1]
    # Farklı alan adlarını dene
    for key in ("BirimPayDegeri", "FIYAT", "fiyat", "price", "Price"):
        raw = last.get(key)
        if raw is not None:
            try:
                return round(float(str(raw).replace(",", ".")), 6)
            except Exception:
                continue
    return None


# ─────────────────────────────────────────────
#  Yahoo Finance hisse fiyatı
# ─────────────────────────────────────────────
def _fetch_yahoo(symbol: str) -> float | None:
    """Yahoo Finance API'sine direkt istek at."""
    yahoo_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    for base in ["query1", "query2"]:
        url = f"https://{base}.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        try:
            r = requests.get(url, headers=yahoo_headers, timeout=10)
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
    t = ticker.upper()

    if t in TEFAS_FUNDS:
        price = _fetch_tefas(t)
        if price is None:
            logger.warning(f"TEFAS fiyat alınamadı: {t}")
        return price

    price = _fetch_yahoo(f"{t}.IS")
    if price is not None:
        return price

    # Yahoo'da yoksa TEFAS'ta dene
    price = _fetch_tefas(t)
    if price is not None:
        logger.info(f"{t} TEFAS'ta bulundu.")
    return price


# ─────────────────────────────────────────────
#  Toplu fiyat çek
# ─────────────────────────────────────────────
def get_prices_bulk(tickers: list[str]) -> dict[str, float | None]:
    return {ticker: get_price(ticker) for ticker in tickers}
