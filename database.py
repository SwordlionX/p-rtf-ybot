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

    # Mevcut pozisyon var mı?
    c.execute(
        "SELECT quantity, avg_cost FROM holdings WHERE user_id = ? AND ticker = ?",
        (user_id, ticker),
    )
    row = c.fetchone()

    if row:
        old_qty, old_cost = row
        new_qty = old_qty + quantity
        # Ağırlıklı ortalama maliyet
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
    """Kullanıcının tüm portföyünü sil."""
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM holdings WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
