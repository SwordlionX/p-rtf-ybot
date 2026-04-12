import sqlite3
import os

DATABASE = os.environ.get("DATABASE_PATH", "portfolio.db")


def init_db() -> None:
    """Veritabanını ve tabloları oluştur."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS holdings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            ticker     TEXT    NOT NULL,
            quantity   REAL    NOT NULL,
            avg_cost   REAL    NOT NULL,
            added_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, ticker)
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS cash (
            user_id    INTEGER PRIMARY KEY,
            amount     REAL    NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Satış geçmişi — gerçekleşen K/Z burada birikir
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            ticker       TEXT    NOT NULL,
            quantity     REAL    NOT NULL,
            avg_cost     REAL    NOT NULL,
            sell_price   REAL    NOT NULL,
            realized_pnl REAL    NOT NULL,
            sold_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Başlangıç sermayesi + tarih
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            user_id          INTEGER PRIMARY KEY,
            starting_capital REAL    NOT NULL DEFAULT 0,
            starting_date    TEXT,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Eski kurulumlar için tarih sütununu ekle (yoksa)
    try:
        c.execute("ALTER TABLE settings ADD COLUMN starting_date TEXT")
    except Exception:
        pass
    conn.commit()
    conn.close()


def _connect():
    return sqlite3.connect(DATABASE)


# ── Hisse işlemleri ──────────────────────────────────────────

def add_holding(user_id: int, ticker: str, quantity: float, avg_cost: float) -> None:
    """Hisse ekle veya mevcut pozisyona ağırlıklı ortalama ile ekle."""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "SELECT quantity, avg_cost FROM holdings WHERE user_id = ? AND ticker = ?",
        (user_id, ticker),
    )
    row = c.fetchone()
    if row:
        old_qty, old_cost = row
        new_qty = old_qty + quantity
        new_avg_cost = (old_qty * old_cost + quantity * avg_cost) / new_qty
        c.execute(
            "UPDATE holdings SET quantity = ?, avg_cost = ? WHERE user_id = ? AND ticker = ?",
            (new_qty, new_avg_cost, user_id, ticker),
        )
    else:
        c.execute(
            "INSERT INTO holdings (user_id, ticker, quantity, avg_cost) VALUES (?, ?, ?, ?)",
            (user_id, ticker, quantity, avg_cost),
        )
    conn.commit()
    conn.close()


def get_holdings(user_id: int) -> list[tuple]:
    """[(ticker, quantity, avg_cost), ...]"""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "SELECT ticker, quantity, avg_cost FROM holdings WHERE user_id = ? ORDER BY ticker",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def remove_holding(user_id: int, ticker: str) -> bool:
    """Hisseyi portföyden sil (K/Z kaydı olmadan). True döner başarılıysa."""
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM holdings WHERE user_id = ? AND ticker = ?", (user_id, ticker))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def sell_holding(
    user_id: int, ticker: str, quantity: float, sell_price: float
) -> dict | None:
    """
    Hisse sat: pozisyonu güncelle, gerçekleşen K/Z'ı trades tablosuna yaz.
    Döndürür: {"realized_pnl": float, "avg_cost": float, "remaining": float}
    Pozisyon yoksa None döner.
    """
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "SELECT quantity, avg_cost FROM holdings WHERE user_id = ? AND ticker = ?",
        (user_id, ticker),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return None

    held_qty, avg_cost = row
    sell_qty = min(quantity, held_qty)  # eldekinden fazla satılamaz
    realized_pnl = (sell_price - avg_cost) * sell_qty
    remaining = held_qty - sell_qty

    # Trades tablosuna kaydet
    c.execute(
        """
        INSERT INTO trades (user_id, ticker, quantity, avg_cost, sell_price, realized_pnl)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, ticker, sell_qty, avg_cost, sell_price, realized_pnl),
    )

    # Holdings güncelle
    if remaining > 0.001:
        c.execute(
            "UPDATE holdings SET quantity = ? WHERE user_id = ? AND ticker = ?",
            (remaining, user_id, ticker),
        )
    else:
        c.execute(
            "DELETE FROM holdings WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        )

    conn.commit()
    conn.close()
    return {"realized_pnl": realized_pnl, "avg_cost": avg_cost, "remaining": remaining, "sold_qty": sell_qty}


def clear_portfolio(user_id: int) -> None:
    """Tüm holdings, cash ve trades sil."""
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM holdings WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM cash WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM trades WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ── Gerçekleşen K/Z ──────────────────────────────────────────

def get_realized_pnl(user_id: int) -> float:
    """Toplam gerçekleşen K/Z."""
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(realized_pnl), 0) FROM trades WHERE user_id = ?", (user_id,))
    total = c.fetchone()[0]
    conn.close()
    return total


def get_trade_history(user_id: int, limit: int = 10) -> list[tuple]:
    """
    Son satışları döndür: [(ticker, quantity, avg_cost, sell_price, realized_pnl, sold_at), ...]
    """
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """
        SELECT ticker, quantity, avg_cost, sell_price, realized_pnl, sold_at
        FROM trades
        WHERE user_id = ?
        ORDER BY sold_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = c.fetchall()
    conn.close()
    return rows


# ── Nakit işlemleri ──────────────────────────────────────────

def set_cash(user_id: int, amount: float) -> None:
    """Nakit bakiyesini ayarla."""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO cash (user_id, amount, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET amount = excluded.amount, updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, amount),
    )
    conn.commit()
    conn.close()


def get_cash(user_id: int) -> float:
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT amount FROM cash WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0


# ── Başlangıç sermayesi + tarih ──────────────────────────────

def set_starting_capital(user_id: int, amount: float, start_date: str) -> None:
    """Başlangıç sermayesi ve tarihi kaydet. start_date: 'YYYY-MM-DD'"""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO settings (user_id, starting_capital, starting_date, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE
            SET starting_capital = excluded.starting_capital,
                starting_date    = excluded.starting_date,
                updated_at       = CURRENT_TIMESTAMP
        """,
        (user_id, amount, start_date),
    )
    conn.commit()
    conn.close()


def get_starting_info(user_id: int) -> dict:
    """Başlangıç sermayesi ve tarihi döndür."""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "SELECT starting_capital, starting_date FROM settings WHERE user_id = ?",
        (user_id,),
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {"capital": row[0], "date": row[1]}
    return {"capital": 0.0, "date": None}
