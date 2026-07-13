from decimal import Decimal
from pathlib import Path

from fixtures.brubank_pages import PAGES as BRUBANK_PAGES
from fixtures.galicia_pages import PAGES as GALICIA_PAGES
from moneytrail import categorize, reconcile
from moneytrail.ingest import import_parsed
from moneytrail.parsers.brubank_tarjeta import BrubankTarjetaParser
from moneytrail.parsers.galicia_caja_ahorro import GaliciaCajaAhorroParser
from moneytrail.report.sankey import NODE_SAVINGS, build_sankey

RULES = categorize.load_rules(Path(__file__).parent.parent / "rules" / "categories.yaml")


def _setup(conn):
    import_parsed(conn, GaliciaCajaAhorroParser().parse(GALICIA_PAGES)[0], "h1", "g.pdf")
    import_parsed(conn, BrubankTarjetaParser().parse(BRUBANK_PAGES)[0], "h2", "b.pdf")
    categorize.apply_rules(conn, RULES)
    reconcile.reconcile(conn)


def test_flows_basics(conn):
    _setup(conn)
    data = build_sankey(conn, usd_rate=Decimal(1000))

    # Ingresos → cuenta, separados por fuente
    assert data.flows[("Sueldo", "Galicia Caja de Ahorro")] == Decimal("62000.00")
    assert data.flows[("Reintegros", "Galicia Caja de Ahorro")] == Decimal("80000.00")

    # Gasto con subcategoría: cuenta → top y top → sub por el mismo monto
    assert data.flows[("Galicia Caja de Ahorro", "Transporte")] == Decimal("21000.00")
    assert data.flows[("Transporte", "Transporte · Estacionamiento")] == Decimal("21000.00")

    # USD convertido al tipo de cambio dado (consumo Anthropic de U$S 20)
    assert data.flows[("Brubank Tarjeta de Crédito", "Suscripciones")] == Decimal("20000.00") + Decimal("10000.00")

    # Los flujos internos no aparecen como gasto
    assert all("TRANSF" not in src and "TRANSF" not in dst for src, dst in data.flows)

    # Totales: no incluyen transferencias ni pagos de tarjeta
    assert data.total_income == Decimal("142006.67")


def test_accounts_are_balanced(conn):
    _setup(conn)
    data = build_sankey(conn, usd_rate=Decimal(1000))
    inflow = {}
    outflow = {}
    for (src, dst), v in data.flows.items():
        outflow[src] = outflow.get(src, Decimal(0)) + v
        inflow[dst] = inflow.get(dst, Decimal(0)) + v
    for node, role in data.node_roles.items():
        if role == "account":
            assert inflow.get(node, Decimal(0)) == outflow.get(node, Decimal(0)), node
    assert (("Galicia Caja de Ahorro", NODE_SAVINGS) in data.flows) or (
        ("Brubank Tarjeta de Crédito", NODE_SAVINGS) in data.flows
    )
