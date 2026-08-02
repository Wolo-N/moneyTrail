"""Servidor local de la app de escritorio.

Sirve la UI en 127.0.0.1 (nunca expuesto a la red) sobre el mismo pipeline que
usa la CLI. Dos decisiones de diseño explican casi todo el archivo:

1. **Una sola llamada para todo el estado** (`/api/state`). Importar, guardar
   una regla o deshacerla devuelven ya el estado nuevo completo, así la UI
   nunca encadena tres round-trips para reflejar un click.
2. **Caché invalidado por versión de datos**. Armar el Sankey y los insights
   recorre todos los movimientos; se cachea contra `db.data_version()`, que
   sólo cambia cuando algo se escribe. Navegar entre meses, abrir el detalle
   de un nodo o cambiar el tipo de cambio no recalcula lo que ya se calculó.
"""

from __future__ import annotations

import calendar
import csv
import io
import socket
import sqlite3
import threading
import webbrowser
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from flask import Flask, Response, jsonify, request

from .. import categorize as cat
from .. import db as dbmod
from .. import guidance
from .. import reconcile as rec
from ..insights import build_insights, known_merchants, suggest_category
from ..models import Kind

STATIC_DIR = Path(__file__).parent / "static"
CACHE_LIMIT = 32
DEFAULT_USD_RATE = "1500"


def create_app(db_path: Path, rules_path: Path) -> Flask:
    app = Flask("moneytrail")
    inbox = db_path.parent / "inbox"
    learned_path = rules_path.parent / "learned.yaml"
    local = threading.local()
    cache: dict[tuple, Any] = {}
    cache_lock = threading.Lock()

    def conn() -> sqlite3.Connection:
        # Una conexión por hilo: `connect()` corre el script de esquema, no
        # tiene sentido pagarlo en cada request.
        if not hasattr(local, "conn"):
            local.conn = dbmod.connect(db_path)
        return local.conn

    def rules() -> list[cat.Rule]:
        return cat.load_rules(learned_path, rules_path)

    def cached(key: tuple, factory: Callable[[], Any]) -> Any:
        with cache_lock:
            if key in cache:
                return cache[key]
        value = factory()
        with cache_lock:
            if len(cache) > CACHE_LIMIT:
                cache.clear()
            cache[key] = value
        return value

    # ---------- helpers de período ----------

    def _range_args() -> tuple[str | None, str | None, Decimal]:
        c = conn()
        date_from = request.args.get("from")
        date_to = request.args.get("to")
        rate_raw = request.args.get("usd_rate")
        # Sin parámetros explícitos usamos lo último que eligió el usuario:
        # abrir la app el mes que viene la deja donde la dejaste.
        if date_from is None:
            date_from = dbmod.get_meta(c, "period_from") or None
        if date_to is None:
            date_to = dbmod.get_meta(c, "period_to") or None
        if rate_raw is None:
            rate_raw = dbmod.get_meta(c, "usd_rate") or DEFAULT_USD_RATE
        if date_from and len(date_from) == 7:
            date_from += "-01"
        if date_to and len(date_to) == 7:
            year, month = int(date_to[:4]), int(date_to[5:7])
            date_to += f"-{calendar.monthrange(year, month)[1]}"
        try:
            rate = Decimal(rate_raw)
        except (InvalidOperation, TypeError):
            rate = Decimal(DEFAULT_USD_RATE)
        return date_from or None, date_to or None, rate

    def _sankey(date_from, date_to, usd_rate):
        from ..report.sankey import build_sankey

        key = ("sankey", dbmod.data_version(conn()), date_from, date_to, str(usd_rate))
        return cached(key, lambda: build_sankey(conn(), date_from, date_to, usd_rate))

    def _insights(date_from, date_to, usd_rate):
        key = ("insights", dbmod.data_version(conn()), date_from, date_to, str(usd_rate))
        return cached(key, lambda: build_insights(conn(), date_from, date_to, usd_rate))

    def _sankey_payload(date_from, date_to, usd_rate) -> dict:
        from ..report.colors import expense_top_colors, node_color

        data = _sankey(date_from, date_to, usd_rate)
        order = ["income", "internal", "opening", "account", "expense_top", "expense_sub", "savings"]
        labels = sorted(data.node_roles, key=lambda n: order.index(data.node_roles[n]))
        index = {label: i for i, label in enumerate(labels)}
        tops_light = expense_top_colors(data, dark=False)
        tops_dark = expense_top_colors(data, dark=True)
        return {
            "nodes": [
                {
                    "label": label,
                    "role": data.node_roles[label],
                    "colorLight": node_color(data, label, tops_light, dark=False),
                    "colorDark": node_color(data, label, tops_dark, dark=True),
                    "drillable": bool(data.node_txs.get(label)),
                    "n": len(data.node_txs.get(label, [])),
                }
                for label in labels
            ],
            "links": [
                {"source": index[src], "target": index[dst], "value": float(value)}
                for (src, dst), value in sorted(data.flows.items(), key=lambda kv: -kv[1])
            ],
            "totals": {
                "income": float(data.total_income),
                "expense": float(data.total_expense),
                "savings": float(data.total_income - data.total_expense),
            },
            "usd_converted": float(data.usd_converted),
            "usd_rate": float(usd_rate),
        }

    def _state_payload() -> dict:
        c = conn()
        date_from, date_to, usd_rate = _range_args()
        months = [r[0] for r in c.execute("SELECT DISTINCT substr(date, 1, 7) FROM tx ORDER BY 1")]

        # Categorías ordenadas por uso: la UI ofrece las primeras como chips de
        # un click y el resto queda en el buscador.
        usage = {
            r[0]: r[1]
            for r in c.execute("SELECT category, COUNT(*) FROM tx WHERE category IS NOT NULL GROUP BY category")
        }
        for rule in rules():
            if rule.category:
                usage.setdefault(rule.category, 0)
        categories = sorted(usage, key=lambda name: (-usage[name], name))

        unmatched = [
            dict(r)
            for r in c.execute(
                """SELECT tx.date, tx.description, tx.amount, tx.currency, account.label AS account_label
                   FROM tx JOIN account ON account.id = tx.account_id
                   WHERE tx.kind IN (?, ?)
                     AND tx.id NOT IN (SELECT tx_out_id FROM transfer_link)
                     AND tx.id NOT IN (SELECT tx_in_id FROM transfer_link)
                   ORDER BY tx.date""",
                (str(Kind.TRANSFER_INTERNAL), str(Kind.CARD_PAYMENT)),
            )
        ]
        # Sugerencia por fila: si ese comercio ya se clasificó antes, o si
        # parece una transferencia a una persona. Ahorra leer 6 chips iguales.
        uncategorized = cat.uncategorized_summary(c)
        known = known_merchants(c)
        for row in uncategorized:
            row["suggested"] = suggest_category(row["description"], row["counterparty"], known, categories)

        learned = cat.read_learned(learned_path)
        return {
            "version": dbmod.data_version(c),
            "period": {"from": date_from, "to": date_to, "usd_rate": float(usd_rate)},
            "months": months,
            "accounts": guidance.account_coverage(c),
            "categories": categories,
            "uncategorized": uncategorized,
            "unmatched": unmatched,
            "steps": guidance.next_steps(c),
            "health": guidance.health(c),
            "last_learned": learned[0] if learned else None,
            "sankey": _sankey_payload(date_from, date_to, usd_rate),
            "insights": _insights(date_from, date_to, usd_rate),
        }

    # ---------- endpoints ----------

    @app.get("/")
    def index() -> Response:
        return Response((STATIC_DIR / "index.html").read_text(), mimetype="text/html")

    @app.get("/api/state")
    def api_state():
        return jsonify(_state_payload())

    @app.post("/api/settings")
    def api_settings():
        data = request.get_json(force=True) or {}
        c = conn()
        for key in ("period_from", "period_to", "usd_rate"):
            if key in data and data[key] is not None:
                dbmod.set_meta(c, key, str(data[key]))
        return jsonify({"ok": True})

    @app.post("/api/import")
    def api_import():
        from ..ingest import import_file  # diferido: carga pdfplumber

        c = conn()
        results = []
        for f in request.files.getlist("files"):
            name = Path(f.filename or "").name
            if not name.lower().endswith(".pdf"):
                results.append({"source": name or "(sin nombre)", "status": "error", "error": "No es un PDF"})
                continue
            inbox.mkdir(parents=True, exist_ok=True)
            dest = inbox / name
            f.save(dest)
            results.append(asdict(import_file(c, dest)))
        categorized = cat.apply_rules(c, rules())
        links = rec.reconcile(c)
        return jsonify(
            {
                "results": results,
                "categorized": categorized,
                "new_links": links.new_links,
                "state": _state_payload(),
            }
        )

    @app.post("/api/rule")
    def api_rule():
        data = request.get_json(force=True)
        match_text = (data.get("match") or "").strip()
        category = (data.get("category") or "").strip()
        if not match_text or not category:
            return jsonify({"error": "Faltan 'match' o 'category'"}), 400
        cat.append_learned(learned_path, match_text, category)
        # Sobre todos los movimientos, no sólo los sin categorizar: clickear una
        # categoría también sirve para corregir una clasificación que ya existía.
        updated = cat.apply_rules(conn(), rules(), only_uncategorized=False)
        return jsonify({"updated": updated, "state": _state_payload()})

    @app.post("/api/rule/undo")
    def api_rule_undo():
        removed = cat.pop_learned(learned_path)
        if removed is None:
            return jsonify({"error": "No hay nada para deshacer"}), 400
        cat.recategorize(conn(), rules())
        return jsonify({"undone": removed, "state": _state_payload()})

    @app.get("/api/drill")
    def api_drill():
        node = request.args.get("node") or ""
        date_from, date_to, usd_rate = _range_args()
        c = conn()
        data = _sankey(date_from, date_to, usd_rate)
        if node not in data.node_roles:
            return jsonify({"error": f"Nodo desconocido: {node}"}), 404
        tx_ids = data.node_txs.get(node, [])
        txs = []
        if tx_ids:
            placeholders = ",".join("?" * len(tx_ids))
            rows = c.execute(
                f"""SELECT tx.id, tx.date, tx.description, tx.counterparty, tx.amount,
                           tx.currency, tx.category, tx.kind, account.label AS account_label
                    FROM tx JOIN account ON account.id = tx.account_id
                    WHERE tx.id IN ({placeholders})
                    ORDER BY tx.date, tx.id""",
                tx_ids,
            ).fetchall()
            txs = [dict(r) for r in rows]
        return jsonify({"node": node, "role": data.node_roles[node], "transactions": txs})

    @app.get("/api/transactions")
    def api_transactions():
        """Buscador libre sobre los movimientos del período."""
        date_from, date_to, _ = _range_args()
        q = (request.args.get("q") or "").strip()
        category = request.args.get("category") or ""
        account = request.args.get("account") or ""
        limit = min(int(request.args.get("limit") or 300), 2000)

        sql = """SELECT tx.id, tx.date, tx.description, tx.counterparty, tx.amount, tx.currency,
                        tx.category, tx.kind, account.label AS account_label
                 FROM tx JOIN account ON account.id = tx.account_id WHERE 1=1"""
        params: list[Any] = []
        if date_from:
            sql += " AND tx.date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND tx.date <= ?"
            params.append(date_to)
        if q:
            sql += " AND (tx.description LIKE ? OR tx.counterparty LIKE ? OR tx.detail LIKE ?)"
            params += [f"%{q}%"] * 3
        if category:
            sql += " AND tx.category = ?" if category != "__none__" else " AND tx.category IS NULL"
            if category != "__none__":
                params.append(category)
        if account:
            sql += " AND account.label = ?"
            params.append(account)
        rows = conn().execute(sql + " ORDER BY tx.date DESC, tx.id DESC LIMIT ?", [*params, limit]).fetchall()
        return jsonify({"transactions": [dict(r) for r in rows], "limit": limit})

    @app.get("/api/export.csv")
    def api_export():
        date_from, date_to, _ = _range_args()
        rows = dbmod.fetch_txs(conn(), date_from, date_to)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["fecha", "cuenta", "descripcion", "contraparte", "monto", "moneda", "categoria", "tipo"])
        for r in rows:
            writer.writerow(
                [
                    r["date"], r["account_label"], r["description"], r["counterparty"],
                    r["amount"], r["currency"], r["category"] or "", r["kind"],
                ]
            )
        name = f"moneytrail_{date_from or 'inicio'}_{date_to or 'hoy'}.csv"
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/static/plotly.js")
    def plotly_js() -> Response:
        # Servida local para que la app funcione offline, sin CDN.
        from plotly.offline import get_plotlyjs

        resp = Response(get_plotlyjs(), mimetype="application/javascript")
        resp.cache_control.max_age = 86400
        return resp

    @app.get("/report")
    def report_view() -> Response:
        from ..report import render_report  # diferido: carga plotly

        date_from, date_to, usd_rate = _range_args()
        return Response(render_report(conn(), date_from, date_to, usd_rate), mimetype="text/html")

    return app


def run_server(db_path: Path, rules_path: Path, port: int = 0, open_browser: bool = True) -> None:
    app = create_app(db_path, rules_path)
    if port == 0:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    print(f"moneyTrail corriendo en {url} — cerrá esta ventana para salir.")
    if open_browser:
        threading.Timer(0.7, webbrowser.open, args=(url,)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
