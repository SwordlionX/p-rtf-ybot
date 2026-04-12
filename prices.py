import logging
import yfinance as yf

logger = logging.getLogger(__name__)


def get_price(ticker: str) -> float | None:
    """
    Yahoo Finance üzerinden BIST hisse fiyatını çek.
    BIST hisseleri için '.IS' uzantısı eklenir (ör: GARAN → GARAN.IS).
    Hafta sonu / tatil günlerinde son kapanış fiyatı döner.
    """
    symbol = f"{ticker.upper()}.IS"
    try:
        stock = yf.Ticker(symbol)

        # Önce fast_info dene (attribute olarak, dict değil)
        try:
            price = stock.fast_info.last_price
            if price and price > 0:
                return round(float(price), 4)
        except Exception:
            pass

        # Fallback: son 5 günlük geçmiş (hafta sonu / tatil günleri için)
        hist = stock.history(period="5d", auto_adjust=True)
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
            period="5d",          # hafta sonu için 5 güne genişlettik
            auto_adjust=True,
            progress=False,
            threads=True,
        )

        if data.empty:
            # Toplu çekme başarısız olduysa teker teker dene
            for ticker in tickers:
                results[ticker] = get_price(ticker)
            return results

        close = data["Close"]

        for ticker, symbol in zip(tickers, symbols):
            try:
                if len(tickers) == 1:
                    series = close
                else:
                    series = close[symbol]
                price = float(series.dropna().iloc[-1])
                results[ticker] = round(price, 4) if price > 0 else None
            except Exception:
                # Toplu çekmede hata varsa teker teker dene
                results[ticker] = get_price(ticker)

    except Exception as e:
        logger.error(f"Toplu fiyat hatası: {e}")
        for ticker in tickers:
            results[ticker] = get_price(ticker)

    return results
