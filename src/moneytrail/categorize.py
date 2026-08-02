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


def load_rules(*paths: Path) -> list[Rule]:
    """Carga una o más listas de reglas, en orden (la primera que matchea gana).

    La UI escribe las reglas que vas creando con un click en su propio archivo
    (`learned.yaml`) y se cargan **antes** que las curadas a mano: son literales
    específicos y deben poder ganarle a un patrón genérico. Además así el
    archivo que editás vos nunca se toca por código y se puede deshacer.
    """
    rules = []
    for path in paths:
        if not path.exists():
            continue
        raw = yaml.safe_load(path.read_text()) or []
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


LEARNED_HEADER = (
    "# Reglas que fuiste creando desde la app con un click.\n"
    "# La más reciente queda arriba y gana: si volvés a clasificar un comercio,\n"
    "# tu última decisión pisa a la anterior. Se cargan antes que categories.yaml.\n"
    "# Podés editarlas o borrarlas a mano.\n"
)


def read_learned(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text()) or []


def write_learned(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(entries, allow_unicode=True, sort_keys=False) if entries else ""
    path.write_text(LEARNED_HEADER + body)


def append_learned(path: Path, match: str, category: str, literal: bool = True) -> dict:
    """Agrega una regla aprendida al tope y la devuelve.

    Va primera porque la última decisión tiene que ganar: si reclasificás un
    comercio que ya tenía categoría, la nueva elección debe aplicarse. Por lo
    mismo se descarta cualquier regla previa sobre el mismo texto, en vez de
    dejar dos reglas contradictorias.

    `literal` escapa el texto para que un comercio con caracteres de regex
    ('Payu*Ar*Uber') se busque tal cual y no reviente al compilar.
    """
    pattern = re.escape(match) if literal else match
    entry = {"match": pattern, "category": category, "label": match}
    entries = [e for e in read_learned(path) if e.get("match") != pattern]
    write_learned(path, [entry, *entries])
    return entry


def pop_learned(path: Path) -> dict | None:
    """Quita la regla aprendida más reciente (deshacer) y la devuelve."""
    entries = read_learned(path)
    if not entries:
        return None
    removed = entries.pop(0)
    write_learned(path, entries)
    return removed


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
    if updated:
        db.bump_version(conn)
    return updated


def recategorize(conn: sqlite3.Connection, rules: list[Rule]) -> int:
    """Recalcula las categorías desde cero. Necesario al deshacer una regla:
    borrar la regla no alcanza, hay que soltar las categorías que había puesto
    y volver a pasar todas las reglas que quedan."""
    conn.execute("UPDATE tx SET category = NULL")
    conn.commit()
    updated = apply_rules(conn, rules, only_uncategorized=False)
    db.bump_version(conn)
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
