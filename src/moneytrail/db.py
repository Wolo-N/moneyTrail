"""Esquema y acceso a SQLite. Los montos se guardan como TEXT (Decimal serializado)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .models import AccountInfo, Kind, Movement, ParsedStatement, dedupe_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY,
    bank TEXT NOT NULL,
    product TEXT NOT NULL,
    currency TEXT NOT NULL,
    label TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS statement (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES account(id),
    file_hash TEXT NOT NULL UNIQUE,
    source_file TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    opening_balance TEXT,
    closing_balance TEXT,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tx (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statement(id),
    account_id INTEGER NOT NULL REFERENCES account(id),
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    counterparty TEXT NOT NULL DEFAULT '',
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    ref TEXT NOT NULL DEFAULT '',
    dedupe_hash TEXT NOT NULL UNIQUE,
    category TEXT,
    kind TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON tx(date);
CREATE INDEX IF NOT EXISTS idx_tx_category ON tx(category);
CREATE INDEX IF NOT EXISTS idx_tx_kind ON tx(kind);
CREATE INDEX IF NOT EXISTS idx_tx_account ON tx(account_id);
CREATE TABLE IF NOT EXISTS transfer_link (
    id INTEGER PRIMARY KEY,
    tx_out_id INTEGER NOT NULL UNIQUE REFERENCES tx(id),
    tx_in_id INTEGER NOT NULL UNIQUE REFERENCES tx(id),
    confidence REAL NOT NULL
);
-- Preferencias de la UI (tipo de cambio, último período elegido...) y el
-- contador de versión de los datos, que invalida los cachés de lectura.
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def data_version(conn: sqlite3.Connection) -> int:
    """Versión de los datos: cambia con cada escritura. Las lecturas caras
    (armado del Sankey, insights) se cachean contra este número, así navegar
    entre meses o abrir el detalle no recalcula nada."""
    return int(get_meta(conn, "data_version", "0"))


def bump_version(conn: sqlite3.Connection) -> int:
    version = data_version(conn) + 1
    set_meta(conn, "data_version", str(version))
    return version


def get_or_create_account(conn: sqlite3.Connection, info: AccountInfo) -> int:
    row = conn.execute("SELECT id FROM account WHERE label = ?", (info.label,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO account (bank, product, currency, label) VALUES (?, ?, ?, ?)",
        (info.bank, info.product, info.currency, info.label),
    )
    return cur.lastrowid


def statement_exists(conn: sqlite3.Connection, file_hash: str) -> bool:
    return conn.execute("SELECT 1 FROM statement WHERE file_hash = ?", (file_hash,)).fetchone() is not None


def insert_statement(
    conn: sqlite3.Connection, account_id: int, stmt: ParsedStatement, file_hash: str, source_file: str
) -> int:
    cur = conn.execute(
        """INSERT INTO statement
           (account_id, file_hash, source_file, period_start, period_end,
            opening_balance, closing_balance, imported_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            account_id,
            file_hash,
            source_file,
            stmt.period_start.isoformat(),
            stmt.period_end.isoformat(),
            str(stmt.opening_balance) if stmt.opening_balance is not None else None,
            str(stmt.closing_balance) if stmt.closing_balance is not None else None,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    return cur.lastrowid


def insert_movement(
    conn: sqlite3.Connection, statement_id: int, account_id: int, account_label: str, mv: Movement
) -> bool:
    """Inserta un movimiento; devuelve False si ya existía (dedupe)."""
    kind = mv.kind or (Kind.INCOME if mv.amount > 0 else Kind.EXPENSE)
    cur = conn.execute(
        """INSERT OR IGNORE INTO tx
           (statement_id, account_id, date, description, detail, counterparty,
            amount, currency, ref, dedupe_hash, category, kind)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
        (
            statement_id,
            account_id,
            mv.date.isoformat(),
            mv.description,
            mv.detail,
            mv.counterparty,
            str(mv.amount),
            mv.currency,
            mv.ref,
            dedupe_hash(account_label, mv),
            str(kind),
        ),
    )
    return cur.rowcount == 1


def fetch_txs(conn: sqlite3.Connection, date_from: str | None = None, date_to: str | None = None) -> list[sqlite3.Row]:
    q = """SELECT tx.*, account.label AS account_label, account.product AS account_product
           FROM tx JOIN account ON account.id = tx.account_id WHERE 1=1"""
    params: list[str] = []
    if date_from:
        q += " AND tx.date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND tx.date <= ?"
        params.append(date_to)
    return conn.execute(q + " ORDER BY tx.date, tx.id", params).fetchall()


def fetch_links(conn: sqlite3.Connection) -> dict[int, int]:
    """Devuelve {tx_out_id: tx_in_id} de las conciliaciones existentes."""
    return {r["tx_out_id"]: r["tx_in_id"] for r in conn.execute("SELECT tx_out_id, tx_in_id FROM transfer_link")}


def amount(row: sqlite3.Row) -> Decimal:
    return Decimal(row["amount"])
