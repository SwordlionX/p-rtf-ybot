import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# TEFAS'tan çekilecek fon kodları
TEFAS_FUNDS = {"NSP", "TTE", "MAC", "GAF", "IEF"}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9",
}


# ─────────────────────────────────────────────
#  TEFAS fon fiyatı (session ile cookie alarak)
# ─────────────────────────────────────────────
def _fetch_tefas(fund_code: str) -> float | None:
    code     = fund_code.upper()
    today    = datetime.now().strftime("%d.%m.%Y")
    week_ago = (datetime.now() - timedelta(days=10)).strftime("%d.%m.%Y")

    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)

    # Önce ana sayfayı ziyaret et → cookie al
    try:
        session.get(
            f"https://www.tefas.gov.tr/FonAnaliz.aspx?FonKod={code}",
            timeout=10,
        )
    except Exception as e:
        logger.debug(f"TEFAS ana sayfa hatası: {e}")

    payload = {
        "fontip":    "YAT",
        "sfonkod":   code,
        "bastarih":  week_ago,
        "bittarih":  today,
        "islemtipi": "I",
    }
    api_headers = {
        "Content-Type":     "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer":          f"https://www.tefas.gov.tr/FonAnaliz.aspx?FonKod={code}",
        "Origin":           "https://www.tefas.gov.tr",
        "Accept":           "application/json, text/javascript, */*; q=0.01",
    }

    for method in ("post", "get"):
        try:
            if method == "post":
                r = session.post(
                    "https://www.tefas.gov.tr/api/DB/BindHistoryInfo",
                    data=payload, headers=api_headers, timeout=15,
                )
            else:
                r = session.get(
                    "https://www.tefas.gov.tr/api/DB/BindHistoryInfo",
                    params=payload, headers=api_headers, timeout=15,
                )
            r.raise_for_status()
            data = r.json()
            price = _parse_tefas(data)
            if price:
                logger.info(f"TEFAS {code}: {price} ({method.upper()})")
                return price
        except Exception as e:
            logger.debug(f"TEFAS {method.upper()} hatası ({code}): {e}")

    logger.warning(f"TEFAS tüm denemeler başarısız: {code}")
    return None


def _parse_tefas(data: dict) -> float | None:
    rows = data.get("data", [])
    if not rows:
        return None
    last = rows[-1]
    for key in ("BirimPayDegeri", "FIYAT", "fiyat", "price"):
        raw = last.get(key)
        if raw is not None:
            try:
                val = float(str(raw).replace(",", "."))
                if 0 < val < 1000:   # fon birim payı makul aralık
                    return round(val, 6)
            except Exception:
                continue
    return None


# ─────────────────────────────────────────────
#  Yahoo Finance hisse fiyatı
# ─────────────────────────────────────────────
def _fetch_yahoo(symbol: str) -> float | None:
    headers = {**BROWSER_HEADERS, "Accept": "application/json"}
    for base in ["query1", "query2"]:
        url = f"https://{base}.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        try:
            r = requests.get(url, headers=headers, timeout=10)
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
#  Dışa açık fonksiyonlar
# ─────────────────────────────────────────────
def is_fund(ticker: str) -> bool:
    """Verilen ticker bir TEFAS fonu mu?"""
    return ticker.upper() in TEFAS_FUNDS


def get_price(ticker: str) -> float | None:
    t = ticker.upper()
    if t in TEFAS_FUNDS:
        price = _fetch_tefas(t)
        if price is None:
            logger.warning(f"TEFAS fiyat alınamadı: {t}")
        return price

    # Hisse senedi → Yahoo Finance
    price = _fetch_yahoo(f"{t}.IS")
    if price is not None:
        return price

    # Yahoo'da yoksa TEFAS'ta bak (kullanıcı fon eklemiş olabilir)
    return _fetch_tefas(t)


def get_prices_bulk(tickers: list[str]) -> dict[str, float | None]:
    return {ticker: get_price(ticker) for ticker in tickers}
