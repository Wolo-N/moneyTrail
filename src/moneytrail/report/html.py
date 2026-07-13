"""Render del reporte: Sankey (Plotly) + tablas, en un HTML estático auto-contenido."""

from __future__ import annotations

import html
import sqlite3
from datetime import datetime
from decimal import Decimal

import plotly.graph_objects as go

from .. import db
from ..categorize import uncategorized_summary
from ..models import Kind
from .sankey import SankeyData, build_sankey, category_totals

# Paleta categórica validada (dataviz reference palette, modo claro).
# Roles fijos: el color sigue al tipo de nodo, no a su posición.
ROLE_COLORS = {
    "income": "#008300",  # slot 4 (green)
    "account": "#2a78d6",  # slot 1 (blue)
    "savings": "#1baf7a",  # slot 2 (aqua)
    "opening": "#898781",  # muted ink
    "internal": "#898781",
}
# Categorías de gasto: slots categóricos restantes en orden fijo; el sobrante va a gris.
EXPENSE_SLOTS = ["#eda100", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834", "#0d366b", "#104281"]
MUTED = "#898781"
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"


def _fmt(value: Decimal) -> str:
    """$ 1.234.567,89 (formato es-AR)."""
    q = f"{value:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"$ {q}"


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def _node_colors(data: SankeyData, labels: list[str]) -> list[str]:
    expense_tops = sorted(
        {n for n, role in data.node_roles.items() if role == "expense_top"},
        key=lambda n: -sum(v for (s, d), v in data.flows.items() if d == n),
    )
    top_color = {
        top: (EXPENSE_SLOTS[i] if i < len(EXPENSE_SLOTS) else MUTED) for i, top in enumerate(expense_tops)
    }
    colors = []
    for label in labels:
        role = data.node_roles[label]
        if role == "expense_top":
            colors.append(top_color[label])
        elif role == "expense_sub":
            colors.append(top_color.get(label.split(" · ")[0], MUTED))
        else:
            colors.append(ROLE_COLORS[role])
    return colors


def sankey_figure(data: SankeyData) -> go.Figure:
    labels = sorted(data.node_roles, key=lambda n: ["income", "internal", "opening", "account", "expense_top", "expense_sub", "savings"].index(data.node_roles[n]))
    index = {label: i for i, label in enumerate(labels)}
    colors = _node_colors(data, labels)
    sources, targets, values, link_colors = [], [], [], []
    for (src, dst), value in sorted(data.flows.items(), key=lambda kv: -kv[1]):
        sources.append(index[src])
        targets.append(index[dst])
        values.append(float(value))
        link_colors.append(_rgba(colors[index[src]], 0.30))

    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            node=dict(
                label=labels,
                color=colors,
                pad=18,
                thickness=14,
                line=dict(width=0),
                hovertemplate="%{label}<br>%{value} ARS<extra></extra>",
            ),
            link=dict(
                source=sources,
                target=targets,
                value=values,
                color=link_colors,
                hovertemplate="%{source.label} → %{target.label}<br>%{value} ARS<extra></extra>",
            ),
        )
    )
    fig.update_layout(
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', size=13, color=INK),
        paper_bgcolor=SURFACE,
        margin=dict(l=8, r=8, t=8, b=8),
        height=560,
        separators=",.",
    )
    return fig


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="tbl-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def render_report(
    conn: sqlite3.Connection,
    date_from: str | None = None,
    date_to: str | None = None,
    usd_rate: Decimal = Decimal(1),
) -> str:
    data = build_sankey(conn, date_from, date_to, usd_rate)
    fig_html = (
        # plotly.js incrustado: el reporte funciona offline, sin depender de un CDN
        sankey_figure(data).to_html(full_html=False, include_plotlyjs=True, config={"displayModeBar": False})
        if data.flows
        else "<p>No hay movimientos en el período.</p>"
    )

    cats = category_totals(conn, date_from, date_to, usd_rate)
    cat_rows = [[c, _fmt(v)] for c, v in cats]

    pending = uncategorized_summary(conn)
    pending_rows = [
        [p["description"], p["counterparty"] or "—", str(p["n"]), f"{p['approx_total']:,.0f} {p['currency']}"]
        for p in pending
    ]

    unmatched = conn.execute(
        """SELECT tx.date, tx.description, tx.amount, tx.currency, account.label AS account_label
           FROM tx JOIN account ON account.id = tx.account_id
           WHERE tx.kind IN (?, ?)
             AND tx.id NOT IN (SELECT tx_out_id FROM transfer_link)
             AND tx.id NOT IN (SELECT tx_in_id FROM transfer_link)
           ORDER BY tx.date""",
        (str(Kind.TRANSFER_INTERNAL), str(Kind.CARD_PAYMENT)),
    ).fetchall()
    unmatched_rows = [
        [u["date"], u["description"], _fmt(Decimal(u["amount"])) if u["currency"] == "ARS" else f"U$S {u['amount']}", u["account_label"]]
        for u in unmatched
    ]

    period = f"{date_from or 'inicio'} → {date_to or 'hoy'}"
    savings = data.total_income - data.total_expense
    usd_note = (
        f"<p class='note'>Incluye U$S {data.usd_converted} convertidos a ARS a {_fmt(usd_rate)} por dólar.</p>"
        if data.usd_converted
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>moneyTrail — {html.escape(period)}</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #f9f9f7; color: {INK};
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  h2 {{ font-size: 1.05rem; margin: 32px 0 8px; }}
  .sub {{ color: {INK_2}; margin: 0 0 20px; }}
  .note {{ color: {INK_2}; font-size: 0.85rem; }}
  .tiles {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }}
  .tile {{ background: {SURFACE}; border: 1px solid rgba(11,11,11,0.10); border-radius: 8px;
           padding: 12px 18px; min-width: 180px; }}
  .tile .k {{ color: {INK_2}; font-size: 0.8rem; }}
  .tile .v {{ font-size: 1.35rem; margin-top: 2px; }}
  .tile .v.pos {{ color: #006300; }}
  .card {{ background: {SURFACE}; border: 1px solid rgba(11,11,11,0.10); border-radius: 8px; padding: 8px; }}
  .tbl-wrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; background: {SURFACE};
           border: 1px solid rgba(11,11,11,0.10); border-radius: 8px; }}
  th, td {{ text-align: left; padding: 7px 12px; border-bottom: 1px solid #e1e0d9;
            font-variant-numeric: tabular-nums; white-space: nowrap; }}
  th {{ color: {INK_2}; font-weight: 600; font-size: 0.8rem; }}
  tr:last-child td {{ border-bottom: none; }}
</style></head><body><main>
<h1>moneyTrail</h1>
<p class="sub">Flujo del dinero · período {html.escape(period)} · generado {datetime.now():%Y-%m-%d %H:%M}</p>
<div class="tiles">
  <div class="tile"><div class="k">Ingresos</div><div class="v pos">{_fmt(data.total_income)}</div></div>
  <div class="tile"><div class="k">Gastos</div><div class="v">{_fmt(data.total_expense)}</div></div>
  <div class="tile"><div class="k">Resultado del período</div><div class="v{' pos' if savings >= 0 else ''}">{_fmt(savings)}</div></div>
</div>
<div class="card">{fig_html}</div>
{usd_note}
<h2>Gasto por categoría</h2>
{_table(["Categoría", "Total"], cat_rows) if cat_rows else "<p class='note'>Sin gastos en el período.</p>"}
<h2>Sin categorizar</h2>
{_table(["Descripción", "Contraparte", "Movs.", "Total aprox."], pending_rows) if pending_rows else "<p class='note'>Todo categorizado ✓</p>"}
<h2>Flujos internos sin conciliar</h2>
{_table(["Fecha", "Descripción", "Monto", "Cuenta"], unmatched_rows) if unmatched_rows else "<p class='note'>Todo conciliado ✓</p>"}
</main></body></html>"""
