"""Conciliación de flujos internos: transferencias entre cuentas propias y
pagos de tarjeta. Un egreso (−X) de una cuenta se empareja con el ingreso (+X)
del mismo tipo en otra cuenta dentro de una ventana de días. Los pares quedan
en transfer_link y el reporte los dibuja como flujo cuenta→cuenta en vez de gasto."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from . import db
from .models import Kind

MATCHABLE_KINDS = (str(Kind.TRANSFER_INTERNAL), str(Kind.CARD_PAYMENT))


@dataclass
class ReconcileResult:
    new_links: int
    unmatched_out: int
    unmatched_in: int


def reconcile(conn: sqlite3.Connection, window_days: int = 3) -> ReconcileResult:
    linked = db.fetch_links(conn)
    linked_ins = set(linked.values())
    txs = [t for t in db.fetch_txs(conn) if t["kind"] in MATCHABLE_KINDS]

    outs = [t for t in txs if db.amount(t) < 0 and t["id"] not in linked]
    ins = [t for t in txs if db.amount(t) > 0 and t["id"] not in linked_ins]

    new_links = 0
    used_ins: set[int] = set()
    for out in outs:
        candidates = [
            t
            for t in ins
            if t["id"] not in used_ins
            and t["account_id"] != out["account_id"]
            and t["kind"] == out["kind"]
            and t["currency"] == out["currency"]
            and db.amount(t) == -db.amount(out)
            and abs((date.fromisoformat(t["date"]) - date.fromisoformat(out["date"])).days) <= window_days
        ]
        if not candidates:
            continue
        best = min(
            candidates,
            key=lambda t: abs((date.fromisoformat(t["date"]) - date.fromisoformat(out["date"])).days),
        )
        days = abs((date.fromisoformat(best["date"]) - date.fromisoformat(out["date"])).days)
        conn.execute(
            "INSERT INTO transfer_link (tx_out_id, tx_in_id, confidence) VALUES (?, ?, ?)",
            (out["id"], best["id"], 1.0 - days / (window_days + 1)),
        )
        used_ins.add(best["id"])
        new_links += 1
    conn.commit()

    return ReconcileResult(
        new_links=new_links,
        unmatched_out=len(outs) - new_links,
        unmatched_in=len(ins) - len(used_ins),
    )
