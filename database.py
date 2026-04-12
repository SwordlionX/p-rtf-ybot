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
    conn.commit()
    conn.close()


def _connect():
    return sqlite3.connect(DATABASE)


def add_holding(user_id: int, ticker: str, quantity: float, avg_cost: float) -> None:
    """
    Hisse ekle veya güncelle.
    Aynı hisse varsa ağırlıklı ortalama maliyet hesaplanarak birleştirilir.
    """
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
    """Kullanıcının tüm hisselerini döndür: [(ticker, quantity, avg_cost), ...]"""
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
    """Belirli bir hisseyi sil. Başarılıysa True döndür."""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        "DELETE FROM holdings WHERE user_id = ? AND ticker = ?",
        (user_id, ticker),
    )
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def clear_portfolio(user_id: int) -> None:
    """Kullanıcının tüm hisselerini ve nakitini sil."""
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM holdings WHERE user_id = ?", (user_id,))
    c.execute("DELETE FROM cash WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ── Nakit işlemleri ──────────────────────────────────────────
def set_cash(user_id: int, amount: float) -> None:
    """Nakit bakiyesini ayarla (üzerine yaz)."""
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
    """Kullanıcının nakit bakiyesini döndür."""
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT amount FROM cash WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0
