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
#  TEFAS fon fiyatı
# ─────────────────────────────────────────────
def _fetch_tefas(fund_code: str) -> float | None:
    code = fund_code.upper()
    today = datetime.now().strftime("%d.%m.%Y")
    week_ago = (datetime.now() - timedelta(days=10)).strftime("%d.%m.%Y")

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
        "User-Agent":       BROWSER_HEADERS["User-Agent"],
        "Accept-Language":  "tr-TR,tr;q=0.9",
    }
    url = "https://www.tefas.gov.tr/api/DB/BindHistoryInfo"

    # Yöntem 1: Cookie olmadan direkt POST (tefas-python gibi)
    try:
        r = requests.post(url, data=payload, headers=api_headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        price = _parse_tefas(data, code)
        if price:
            logger.info(f"TEFAS direct {code}: {price}")
            return price
    except Exception as e:
        logger.debug(f"TEFAS direct POST hatası ({code}): {e}")

    # Yöntem 2: Session ile cookie alarak
    try:
        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)
        session.get(
            f"https://www.tefas.gov.tr/FonAnaliz.aspx?FonKod={code}",
            timeout=10,
        )
        r = session.post(url, data=payload, headers=api_headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        price = _parse_tefas(data, code)
        if price:
            logger.info(f"TEFAS session {code}: {price}")
            return price
    except Exception as e:
        logger.debug(f"TEFAS session hatası ({code}): {e}")

    logger.warning(f"TEFAS başarısız: {code}")
    return None


def _parse_tefas(data: dict, code: str = "") -> float | None:
    rows = data.get("data", data.get("result", []))
    if not rows:
        logger.debug(f"TEFAS boş data ({code}). Keys: {list(data.keys())}")
        return None
    last = rows[-1]
    logger.debug(f"TEFAS son satır anahtarları ({code}): {list(last.keys())}")
    for key in ("BirimPayDegeri", "BIRIM_PAY_DEGERI", "birimpaydegeri",
                "FIYAT", "fiyat", "price", "Price", "BPD"):
        raw = last.get(key)
        if raw is not None:
            try:
                val = float(str(raw).replace(",", "."))
                if 0 < val < 500:  # fon birim payı makul aralık
                    logger.info(f"TEFAS {code} → '{key}': {val}")
                    return round(val, 6)
                else:
                    logger.debug(f"TEFAS {code} '{key}' = {val} → aralık dışı, atlandı")
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
        # TEFAS fonları için SADECE TEFAS kullan — Yahoo'ya düşme!
        price = _fetch_tefas(t)
        if price is None:
            logger.warning(f"TEFAS fiyat alınamadı: {t}")
        return price

    # Hisse senedi → Yahoo Finance (.IS uzantısıyla)
    price = _fetch_yahoo(f"{t}.IS")
    if price is not None:
        return price

    # Yahoo'da yoksa TEFAS'a bak
    return _fetch_tefas(t)


def get_prices_bulk(tickers: list[str]) -> dict[str, float | None]:
    return {ticker: get_price(ticker) for ticker in tickers}
