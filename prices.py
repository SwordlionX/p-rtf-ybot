import logging
import yfinance as yf

logger = logging.getLogger(__name__)


def get_price(ticker: str) -> float | None:
    """
    Yahoo Finance üzerinden BIST hisse fiyatını çek.
    BIST hisseleri için '.IS' uzantısı eklenir (ör: GARAN → GARAN.IS).
    Başarısız olursa None döner.
    """
    symbol = f"{ticker.upper()}.IS"
    try:
        stock = yf.Ticker(symbol)
        # fast_info daha hızlı ve önbelleksiz
        price = stock.fast_info.get("last_price")
        if price and price > 0:
            return round(price, 4)

        # Fallback: günlük geçmiş
        hist = stock.history(period="1d", auto_adjust=True)
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 4)

        logger.warning(f"Fiyat alınamadı: {symbol}")
        return None

    except Exception as e:
        logger.error(f"Fiyat hatası ({symbol}): {e}")
        return None


def get_prices_bulk(tickers: list[str]) -> dict[str, float | None]:
    """
    Birden fazla hisse için toplu fiyat çekme (daha verimli).
    Döndürür: {ticker: price}
    """
    if not tickers:
        return {}

    symbols = [f"{t.upper()}.IS" for t in tickers]
    results = {}

    try:
        data = yf.download(
            symbols,
            period="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )

        if data.empty:
            return {t: None for t in tickers}

        close = data["Close"] if len(tickers) > 1 else data[["Close"]]

        for ticker, symbol in zip(tickers, symbols):
            try:
                col = symbol if len(tickers) > 1 else "Close"
                price = float(close[col].dropna().iloc[-1])
                results[ticker] = round(price, 4) if price > 0 else None
            except Exception:
                results[ticker] = None

    except Exception as e:
        logger.error(f"Toplu fiyat hatası: {e}")
        return {t: None for t in tickers}

    return results
