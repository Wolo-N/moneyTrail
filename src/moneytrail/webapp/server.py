"""Servidor local de la app de escritorio.

Sirve la UI en 127.0.0.1 (nunca expuesto a la red) y expone una API mínima
sobre el mismo pipeline que usa la CLI: importar PDFs, ver estado, agregar
reglas de categorización y generar el reporte.
"""

from __future__ import annotations

import calendar
import re
import socket
import threading
import webbrowser
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import yaml
from flask import Flask, Response, jsonify, request

from .. import categorize as cat
from .. import db as dbmod
from .. import reconcile as rec
from ..models import Kind

STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_path: Path, rules_path: Path) -> Flask:
    app = Flask("moneytrail")
    inbox = db_path.parent / "inbox"

    def conn():
        return dbmod.connect(db_path)

    @app.get("/")
    def index() -> Response:
        return Response((STATIC_DIR / "index.html").read_text(), mimetype="text/html")

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
        categorized = cat.apply_rules(c, cat.load_rules(rules_path)) if rules_path.exists() else 0
        links = rec.reconcile(c)
        return jsonify({"results": results, "categorized": categorized, "new_links": links.new_links})

    @app.get("/api/status")
    def api_status():
        c = conn()
        accounts = [
            dict(r)
            for r in c.execute(
                """SELECT account.label, COUNT(DISTINCT statement.id) AS stmts,
                          MIN(statement.period_start) AS d0, MAX(statement.period_end) AS d1,
                          COUNT(tx.id) AS txs
                   FROM account
                   LEFT JOIN statement ON statement.account_id = account.id
                   LEFT JOIN tx ON tx.account_id = account.id
                   GROUP BY account.id"""
            )
        ]
        months = [r[0] for r in c.execute("SELECT DISTINCT substr(date, 1, 7) FROM tx ORDER BY 1")]
        categories = sorted(
            {r[0] for r in c.execute("SELECT DISTINCT category FROM tx WHERE category IS NOT NULL")}
            | {rule.category for rule in (cat.load_rules(rules_path) if rules_path.exists() else []) if rule.category}
        )
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
        return jsonify(
            {
                "accounts": accounts,
                "months": months,
                "categories": categories,
                "uncategorized": cat.uncategorized_summary(c),
                "unmatched": unmatched,
            }
        )

    @app.post("/api/rule")
    def api_rule():
        data = request.get_json(force=True)
        match_text = (data.get("match") or "").strip()
        category = (data.get("category") or "").strip()
        if not match_text or not category:
            return jsonify({"error": "Faltan 'match' o 'category'"}), 400
        entry = yaml.safe_dump(
            [{"match": re.escape(match_text), "category": category}], allow_unicode=True, sort_keys=False
        )
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        with rules_path.open("a") as fh:
            fh.write("\n" + entry)
        updated = cat.apply_rules(conn(), cat.load_rules(rules_path))
        return jsonify({"updated": updated})

    @app.get("/report")
    def report_view() -> Response:
        from ..report import render_report  # diferido: carga plotly

        date_from = request.args.get("from") or None
        date_to = request.args.get("to") or None
        if date_from and len(date_from) == 7:
            date_from += "-01"
        if date_to and len(date_to) == 7:
            year, month = int(date_to[:4]), int(date_to[5:7])
            date_to += f"-{calendar.monthrange(year, month)[1]}"
        usd_rate = Decimal(request.args.get("usd_rate") or "1500")
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
    app.run(host="127.0.0.1", port=port, debug=False)
