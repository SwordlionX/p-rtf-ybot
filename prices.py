import logging
import requests

logger = logging.getLogger(__name__)

# Yahoo Finance'e gerçek tarayıcı gibi görünmek için header
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _fetch_yahoo(symbol: str) -> float | None:
    """Yahoo Finance API'sine direkt istek at (yfinance kütüphanesi bypass)."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&range=5d"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        closes = (
            data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        )
        closes = [c for c in closes if c is not None]
        if closes:
            return round(closes[-1], 4)
    except Exception as e:
        logger.debug(f"Yahoo v8 başarısız ({symbol}): {e}")

    # 2. deneme — farklı endpoint
    url2 = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&range=5d"
    )
    try:
        r = requests.get(url2, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        closes = (
            data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        )
        closes = [c for c in closes if c is not None]
        if closes:
            return round(closes[-1], 4)
    except Exception as e:
        logger.debug(f"Yahoo v8 (query2) başarısız ({symbol}): {e}")

    return None


def get_price(ticker: str) -> float | None:
    """
    BIST hisse fiyatını çek. Hafta sonu / tatil günleri son kapanış döner.
    """
    symbol = f"{ticker.upper()}.IS"
    price = _fetch_yahoo(symbol)
    if price is None:
        logger.warning(f"Fiyat alınamadı: {symbol}")
    return price


def get_prices_bulk(tickers: list[str]) -> dict[str, float | None]:
    """
    Birden fazla hisse için fiyat çek.
    Döndürür: {ticker: price}
    """
    results = {}
    for ticker in tickers:
        results[ticker] = get_price(ticker)
    return results
