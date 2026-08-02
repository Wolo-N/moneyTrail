"""Qué hacer ahora: el panel que hace que el ritual mensual no dependa de
acordarse de nada.

Mira el estado real de los datos (qué cuentas están al día, qué falta
categorizar, qué quedó sin conciliar) y devuelve una lista corta y ordenada
de pasos concretos.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from .categorize import uncategorized_summary
from .models import Kind

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def month_label(month: str) -> str:
    """'2026-06' → 'junio 2026'."""
    year, mon = int(month[:4]), int(month[5:7])
    return f"{MESES[mon - 1]} {year}"


def _prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def _months_between(a: str, b: str) -> int:
    """Cuántos meses hay de `a` a `b` (negativo si `a` es posterior)."""
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return (yb - ya) * 12 + (mb - ma)


def account_coverage(conn: sqlite3.Connection) -> list[dict]:
    """Por cuenta: hasta qué mes hay datos y cuántos extractos se importaron."""
    rows = conn.execute(
        """SELECT account.id, account.label, account.bank, account.currency,
                  COUNT(DISTINCT statement.id) AS stmts,
                  MIN(statement.period_start) AS first_day,
                  MAX(statement.period_end) AS last_day,
                  COUNT(tx.id) AS txs
           FROM account
           LEFT JOIN statement ON statement.account_id = account.id
           LEFT JOIN tx ON tx.account_id = account.id
           GROUP BY account.id
           ORDER BY account.label"""
    ).fetchall()
    return [dict(r) for r in rows]


def next_steps(conn: sqlite3.Connection, today: date | None = None) -> list[dict]:
    """Lista ordenada de acciones pendientes. Vacía = todo al día."""
    today = today or date.today()
    steps: list[dict] = []
    accounts = account_coverage(conn)

    if not accounts:
        return [
            {
                "id": "onboarding",
                "severity": "info",
                "title": "Empezá soltando tus PDFs acá arriba",
                "detail": "Resúmenes de banco y de tarjeta. Podés soltar varios juntos; "
                "si repetís uno, no se duplica nada.",
                "action": "import",
            }
        ]

    # El resumen que ya debería estar: el del mes pasado (el actual todavía
    # no cerró). Se avisa por cuenta y sólo si esa cuenta se venía usando.
    expected = _prev_month(f"{today.year:04d}-{today.month:02d}")
    stale = []
    for acc in accounts:
        if not acc["last_day"]:
            continue
        covered = acc["last_day"][:7]
        missing = _months_between(covered, expected)
        if missing >= 1:
            stale.append({"label": acc["label"], "covered": covered, "missing": missing})

    if stale:
        # Un solo paso con todas las cuentas: cuatro tarjetas casi iguales no
        # se leen, una lista sí.
        stale.sort(key=lambda a: (-a["missing"], a["label"]))
        detalle = " · ".join(
            f"{a['label']} (último: {month_label(a['covered'])})" for a in stale
        )
        # 'resumen' pluraliza con tilde ('resúmenes'): no se arma con sufijos.
        titulo = f"Falta 1 resumen" if len(stale) == 1 else f"Faltan {len(stale)} resúmenes"
        steps.append(
            {
                "id": "import:missing",
                "severity": "warn",
                "title": f"{titulo} de {month_label(expected)}",
                "detail": f"{detalle}. Descargalos del homebanking y soltalos en la zona de arriba.",
                "action": "import",
                "accounts": [a["label"] for a in stale],
            }
        )

    pending = uncategorized_summary(conn)
    if pending:
        total = sum(abs(p["approx_total"] or 0) for p in pending)
        steps.append(
            {
                "id": "categorize",
                "severity": "warn" if len(pending) > 5 else "info",
                "title": f"{len(pending)} gastos sin categorizar",
                "detail": f"Unos $ {total:,.0f} sin clasificar. Un click en la categoría y queda "
                "aprendido para siempre.".replace(",", "."),
                "action": "categorize",
            }
        )

    unmatched = conn.execute(
        """SELECT COUNT(*) FROM tx
           WHERE kind IN (?, ?)
             AND id NOT IN (SELECT tx_out_id FROM transfer_link)
             AND id NOT IN (SELECT tx_in_id FROM transfer_link)""",
        (str(Kind.TRANSFER_INTERNAL), str(Kind.CARD_PAYMENT)),
    ).fetchone()[0]
    if unmatched:
        steps.append(
            {
                "id": "reconcile",
                "severity": "info",
                "title": f"{unmatched} movimientos internos sin par",
                "detail": "Transferencias entre tus cuentas o pagos de tarjeta cuyo otro extremo "
                "todavía no importaste. Se enlazan solos cuando llegue ese resumen.",
                "action": "none",
            }
        )

    if not steps:
        steps.append(
            {
                "id": "ok",
                "severity": "ok",
                "title": "Todo al día",
                "detail": "Tus cuentas están importadas y categorizadas. Volvé el mes que viene "
                "con los resúmenes nuevos.",
                "action": "none",
            }
        )
    return steps


def health(conn: sqlite3.Connection) -> dict:
    """Métricas de confianza del dato, para mostrar junto a los números."""
    total_txs = conn.execute("SELECT COUNT(*) FROM tx").fetchone()[0]
    categorized = conn.execute(
        "SELECT COUNT(*) FROM tx WHERE category IS NOT NULL OR kind IN (?, ?)",
        (str(Kind.TRANSFER_INTERNAL), str(Kind.CARD_PAYMENT)),
    ).fetchone()[0]
    statements = conn.execute("SELECT COUNT(*) FROM statement").fetchone()[0]
    links = conn.execute("SELECT COUNT(*) FROM transfer_link").fetchone()[0]
    return {
        "transactions": total_txs,
        "statements": statements,
        "categorized_pct": round(categorized / total_txs * 100, 1) if total_txs else 0.0,
        "reconciled_links": links,
        "accounts": len(account_coverage(conn)),
    }


def fmt_ars(value: Decimal | float) -> str:
    q = f"{float(value):,.0f}".replace(",", ".")
    return f"$ {q}"
