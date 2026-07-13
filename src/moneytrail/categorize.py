"""Motor de reglas de categorización.

Las reglas viven en rules/categories.yaml: lista ordenada de
  - match: <regex, case-insensitive>
    category: <Top/Sub>      (opcional)
    kind: <kind override>    (opcional)
La primera regla que matchea (sobre descripción + detalle + contraparte) gana.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from . import db
from .models import Kind


@dataclass
class Rule:
    pattern: re.Pattern[str]
    category: str | None
    kind: Kind | None


def load_rules(path: Path) -> list[Rule]:
    raw = yaml.safe_load(path.read_text()) or []
    rules = []
    for i, entry in enumerate(raw):
        if "match" not in entry:
            raise ValueError(f"Regla #{i + 1} sin 'match' en {path}")
        rules.append(
            Rule(
                pattern=re.compile(entry["match"], re.IGNORECASE),
                category=entry.get("category"),
                kind=Kind(entry["kind"]) if entry.get("kind") else None,
            )
        )
    return rules


def match_rule(rules: list[Rule], text: str) -> Rule | None:
    return next((r for r in rules if r.pattern.search(text)), None)


def apply_rules(conn: sqlite3.Connection, rules: list[Rule], only_uncategorized: bool = True) -> int:
    """Aplica las reglas y devuelve cuántos movimientos se actualizaron."""
    where = "WHERE category IS NULL" if only_uncategorized else ""
    updated = 0
    for row in conn.execute(f"SELECT id, description, detail, counterparty, category, kind FROM tx {where}"):
        rule = match_rule(rules, f"{row['description']} {row['detail']} {row['counterparty']}")
        if rule is None:
            continue
        category = rule.category if rule.category is not None else row["category"]
        kind = str(rule.kind) if rule.kind is not None else row["kind"]
        if (category, kind) != (row["category"], row["kind"]):
            conn.execute("UPDATE tx SET category = ?, kind = ? WHERE id = ?", (category, kind, row["id"]))
            updated += 1
    conn.commit()
    return updated


def uncategorized_summary(conn: sqlite3.Connection) -> list[dict]:
    """Movimientos sin categoría (excluyendo flujos internos), agrupados por
    descripción, para decidir qué reglas agregar."""
    rows = conn.execute(
        """SELECT description, counterparty, currency, COUNT(*) AS n,
                  SUM(CAST(amount AS REAL)) AS approx_total
           FROM tx
           WHERE category IS NULL AND kind NOT IN (?, ?)
           GROUP BY description, counterparty, currency
           ORDER BY ABS(SUM(CAST(amount AS REAL))) DESC""",
        (str(Kind.TRANSFER_INTERNAL), str(Kind.CARD_PAYMENT)),
    ).fetchall()
    return [dict(r) for r in rows]


def uncategorized_expense_ratio(conn: sqlite3.Connection) -> tuple[Decimal, Decimal]:
    """(monto sin categorizar, monto total) sobre egresos reales (no internos)."""
    total = uncat = Decimal(0)
    for row in db.fetch_txs(conn):
        if row["kind"] in (str(Kind.TRANSFER_INTERNAL), str(Kind.CARD_PAYMENT)) or db.amount(row) >= 0:
            continue
        total += -db.amount(row)
        if row["category"] is None:
            uncat += -db.amount(row)
    return uncat, total
