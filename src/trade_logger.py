import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

_DB_PATH = Path(__file__).parent / 'trades.db'

_CREATE_SQL = (
    'CREATE TABLE IF NOT EXISTS trades ('
    'id INTEGER PRIMARY KEY AUTOINCREMENT,'
    'symbol TEXT NOT NULL,'
    'strategy TEXT NOT NULL,'
    'order_key TEXT,'
    'entry_price REAL,'
    'exit_price REAL,'
    'quantity INTEGER,'
    'entry_time TEXT,'
    'exit_time TEXT'
    ')'
)


def _get_conn():
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(_CREATE_SQL)
    return conn


def log_trade(symbol: str, strategy: str, order_key: Optional[str] = None, entry_price: Optional[float] = None, exit_price: Optional[float] = None, qty: Optional[int] = None, entry_time: Optional[str] = None, exit_time: Optional[str] = None) -> None:
    """トレード情報を SQLite に記録"""
    conn = _get_conn()
    with conn:
        conn.execute(
            'INSERT INTO trades (symbol, strategy, order_key, entry_price, exit_price, quantity, entry_time, exit_time) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (symbol, strategy, order_key, entry_price, exit_price, qty, entry_time or datetime.utcnow().isoformat(), exit_time or datetime.utcnow().isoformat())
        )
    conn.close() 