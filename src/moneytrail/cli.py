"""CLI de moneyTrail: import / status / reconcile / categorize / report / gui."""

from __future__ import annotations

import calendar
import webbrowser
from decimal import Decimal
from pathlib import Path

import typer

from . import categorize as cat
from . import db as dbmod
from . import reconcile as rec

app = typer.Typer(help="Rastreá a dónde va la plata: de PDFs bancarios a un Sankey.", no_args_is_help=True)

DB_OPT = typer.Option(Path("data/moneytrail.db"), "--db", help="Ruta de la base SQLite")
RULES_OPT = typer.Option(Path("rules/categories.yaml"), "--rules", help="Reglas de categorización")


@app.command("import")
def import_cmd(
    path: Path = typer.Argument(..., help="PDF o directorio con PDFs"),
    db: Path = DB_OPT,
    rules: Path = RULES_OPT,
    archive: bool = typer.Option(False, "--archive", help="Mover los PDFs importados a data/archive/"),
):
    """Importa extractos PDF (idempotente) y categoriza lo nuevo."""
    from .ingest import import_path  # diferido: carga pdfplumber

    conn = dbmod.connect(db)
    results = import_path(conn, path, Path("data/archive") if archive else None)
    for r in results:
        line = {
            "imported": f"✓ {r.source}: {r.new_txs} movimientos nuevos, {r.dup_txs} duplicados ({r.parser})",
            "skipped_duplicate": f"= {r.source}: ya importado, salteado",
            "no_parser": f"? {r.source}: ningún parser reconoce este formato",
            "error": f"✗ {r.source}: {r.error}",
        }[r.status]
        typer.echo(line)
    if rules.exists():
        updated = cat.apply_rules(conn, cat.load_rules(rules.parent / "learned.yaml", rules))
        typer.echo(f"Categorización: {updated} movimientos actualizados")
    linked = rec.reconcile(conn)
    if linked.new_links:
        typer.echo(f"Conciliación: {linked.new_links} flujos internos enlazados")
    if any(r.status == "error" for r in results):
        raise typer.Exit(1)


@app.command()
def status(db: Path = DB_OPT):
    """Cuentas, períodos cubiertos y pendientes."""
    conn = dbmod.connect(db)
    rows = conn.execute(
        """SELECT account.label, COUNT(DISTINCT statement.id) AS stmts,
                  MIN(statement.period_start) AS d0, MAX(statement.period_end) AS d1,
                  COUNT(tx.id) AS txs
           FROM account
           LEFT JOIN statement ON statement.account_id = account.id
           LEFT JOIN tx ON tx.account_id = account.id
           GROUP BY account.id"""
    ).fetchall()
    if not rows:
        typer.echo("Sin datos todavía. Empezá con: moneytrail import <pdf>")
        return
    for r in rows:
        typer.echo(f"• {r['label']}: {r['stmts']} extractos, {r['txs']} movimientos, período {r['d0']} → {r['d1']}")
    uncat, total = cat.uncategorized_expense_ratio(conn)
    if total:
        pct = uncat / total * 100
        typer.echo(f"Sin categorizar: {uncat} de {total} en egresos ({pct:.1f}%)")
    unmatched = rec.reconcile(conn)  # idempotente; refresca y reporta
    if unmatched.unmatched_out or unmatched.unmatched_in:
        typer.echo(
            f"Flujos internos sin conciliar: {unmatched.unmatched_out} salidas, "
            f"{unmatched.unmatched_in} entradas (ver 'moneytrail report')"
        )


@app.command()
def reconcile(db: Path = DB_OPT, window: int = typer.Option(3, help="Ventana de días para matchear")):
    """Enlaza transferencias entre cuentas propias y pagos de tarjeta."""
    conn = dbmod.connect(db)
    result = rec.reconcile(conn, window)
    typer.echo(f"{result.new_links} enlaces nuevos; sin conciliar: {result.unmatched_out} salidas, {result.unmatched_in} entradas")


@app.command()
def categorize(
    db: Path = DB_OPT,
    rules: Path = RULES_OPT,
    review: bool = typer.Option(False, "--review", help="Listar lo que quedó sin categorizar"),
    all_: bool = typer.Option(False, "--all", help="Re-aplicar reglas también a lo ya categorizado"),
):
    """Aplica las reglas de rules/categories.yaml."""
    conn = dbmod.connect(db)
    updated = cat.apply_rules(
        conn, cat.load_rules(rules.parent / "learned.yaml", rules), only_uncategorized=not all_
    )
    typer.echo(f"{updated} movimientos actualizados")
    if review:
        pending = cat.uncategorized_summary(conn)
        if not pending:
            typer.echo("Todo categorizado ✓")
        for p in pending:
            typer.echo(
                f"  {p['description']} | {p['counterparty'] or '—'} | {p['n']} movs | ~{p['approx_total']:,.0f} {p['currency']}"
            )


@app.command()
def gui(
    db: Path = DB_OPT,
    rules: Path = RULES_OPT,
    port: int = typer.Option(0, help="Puerto local (0 = elegir uno libre)"),
    no_browser: bool = typer.Option(False, "--no-browser", help="No abrir el navegador automáticamente"),
):
    """Abre la app de escritorio: drag & drop de PDFs, categorización guiada y reporte."""
    from .webapp.server import run_server  # diferido: carga flask

    run_server(db, rules, port, open_browser=not no_browser)


@app.command()
def report(
    db: Path = DB_OPT,
    date_from: str = typer.Option(None, "--from", help="Fecha desde (YYYY-MM-DD o YYYY-MM)"),
    date_to: str = typer.Option(None, "--to", help="Fecha hasta (YYYY-MM-DD o YYYY-MM)"),
    usd_rate: float = typer.Option(1500.0, "--usd-rate", help="Tipo de cambio ARS por USD para el Sankey"),
    out: Path = typer.Option(Path("report.html"), "--out"),
    open_browser: bool = typer.Option(False, "--open", help="Abrir el reporte al terminar"),
):
    """Genera el reporte HTML con el diagrama de Sankey."""
    from .report import render_report  # diferido: carga plotly

    if date_from and len(date_from) == 7:
        date_from += "-01"
    if date_to and len(date_to) == 7:
        year, month = int(date_to[:4]), int(date_to[5:7])
        date_to += f"-{calendar.monthrange(year, month)[1]}"
    conn = dbmod.connect(db)
    out.write_text(render_report(conn, date_from, date_to, Decimal(str(usd_rate))))
    typer.echo(f"Reporte generado: {out}")
    if open_browser:
        webbrowser.open(out.resolve().as_uri())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
