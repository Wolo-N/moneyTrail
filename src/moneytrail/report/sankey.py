"""Armado de los flujos del Sankey a partir de la DB.

Semántica:
- Ingresos (por subcategoría) → cuenta.
- Cuenta → categoría de gasto (nivel 1) → subcategoría (nivel 2, si hay).
- Flujos internos conciliados → cuenta → cuenta (nunca cuentan como gasto);
  el lado positivo del par se omite para no duplicar.
- Pagos de tarjeta conciliados: el flujo entra a la cuenta-tarjeta y de ahí
  se abre en los consumos reales del resumen.
- Cada cuenta se balancea: el excedente va a 'No gastado (quedó en cuenta)'
  y el faltante sale de 'Saldo inicial'.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from .. import db
from ..models import Kind

UNCATEGORIZED = "Sin categorizar"
NODE_SAVINGS = "No gastado (quedó en cuenta)"
NODE_OPENING = "Saldo inicial"
NODE_OTHER_OWN = "Otras cuentas propias"
NODE_FROM_OTHER = "Desde otras cuentas"
NODE_CARD_NO_DETAIL = "Tarjeta (resumen no importado)"
NODE_CARD_PAY_UNKNOWN = "Pagos desde cuentas no importadas"

EXPENSE_KINDS = (str(Kind.EXPENSE), str(Kind.TAX), str(Kind.FEE), str(Kind.INTEREST), str(Kind.FX))


@dataclass
class SankeyData:
    # (origen, destino) -> monto en ARS
    flows: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    # etiqueta de nodo -> rol ('income'|'account'|'expense_top'|'expense_sub'|'internal'|'savings'|'opening')
    node_roles: dict[str, str] = field(default_factory=dict)
    total_income: Decimal = Decimal(0)
    total_expense: Decimal = Decimal(0)
    usd_converted: Decimal = Decimal(0)  # total USD convertido (para transparentar el TC usado)


def _split_category(category: str | None) -> tuple[str, str | None]:
    if not category:
        return UNCATEGORIZED, None
    top, _, sub = category.partition("/")
    return top, (sub or None)


def build_sankey(
    conn: sqlite3.Connection,
    date_from: str | None = None,
    date_to: str | None = None,
    usd_rate: Decimal = Decimal(1),
) -> SankeyData:
    txs = db.fetch_txs(conn, date_from, date_to)
    links = db.fetch_links(conn)
    linked_in_ids = set(links.values())
    account_by_txid = {t["id"]: t["account_label"] for t in txs}
    data = SankeyData()

    def add(src: str, dst: str, value: Decimal, src_role: str, dst_role: str) -> None:
        if value <= 0:
            return
        data.flows[(src, dst)] = data.flows.get((src, dst), Decimal(0)) + value
        data.node_roles.setdefault(src, src_role)
        data.node_roles.setdefault(dst, dst_role)

    for t in txs:
        value = db.amount(t)
        if t["currency"] == "USD":
            value *= usd_rate
            data.usd_converted += abs(db.amount(t))
        account = t["account_label"]
        kind = t["kind"]

        if kind == str(Kind.INCOME):
            top, sub = _split_category(t["category"])
            source = sub or top  # 'Ingresos/Sueldo' → nodo 'Sueldo'
            add(source, account, value, "income", "account")
            data.total_income += value
        elif kind in EXPENSE_KINDS and value < 0:
            top, sub = _split_category(t["category"])
            add(account, top, -value, "account", "expense_top")
            if sub:
                add(top, f"{top} · {sub}", -value, "expense_top", "expense_sub")
            data.total_expense += -value
        elif kind == str(Kind.TRANSFER_INTERNAL):
            if value < 0:
                dest = account_by_txid.get(links.get(t["id"], -1), NODE_OTHER_OWN)
                add(account, dest, -value, "account", "account" if dest != NODE_OTHER_OWN else "internal")
            elif t["id"] not in linked_in_ids:
                add(NODE_FROM_OTHER, account, value, "internal", "account")
        elif kind == str(Kind.CARD_PAYMENT):
            if value < 0:
                dest = account_by_txid.get(links.get(t["id"], -1), NODE_CARD_NO_DETAIL)
                add(account, dest, -value, "account", "account" if dest != NODE_CARD_NO_DETAIL else "internal")
            elif t["id"] not in linked_in_ids:
                add(NODE_CARD_PAY_UNKNOWN, account, value, "internal", "account")
        elif value > 0:  # positivo con kind de gasto: devolución/ajuste, entra a la cuenta
            add("Devoluciones y ajustes", account, value, "income", "account")

    _balance_accounts(data)
    return data


def _balance_accounts(data: SankeyData) -> None:
    accounts = [n for n, role in data.node_roles.items() if role == "account"]
    inflow: dict[str, Decimal] = defaultdict(Decimal)
    outflow: dict[str, Decimal] = defaultdict(Decimal)
    for (src, dst), value in data.flows.items():
        outflow[src] += value
        inflow[dst] += value
    for account in accounts:
        diff = inflow[account] - outflow[account]
        if diff > 0:
            data.flows[(account, NODE_SAVINGS)] = diff
            data.node_roles.setdefault(NODE_SAVINGS, "savings")
        elif diff < 0:
            data.flows[(NODE_OPENING, account)] = -diff
            data.node_roles.setdefault(NODE_OPENING, "opening")


def category_totals(
    conn: sqlite3.Connection, date_from: str | None = None, date_to: str | None = None, usd_rate: Decimal = Decimal(1)
) -> list[tuple[str, Decimal]]:
    """Gasto por categoría (nivel completo), de mayor a menor, en ARS."""
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for t in db.fetch_txs(conn, date_from, date_to):
        value = db.amount(t)
        if t["kind"] not in EXPENSE_KINDS or value >= 0:
            continue
        if t["currency"] == "USD":
            value *= usd_rate
        totals[t["category"] or UNCATEGORIZED] += -value
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
