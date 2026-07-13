"""Ingesta idempotente, categorización y conciliación sobre la DB."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from fixtures.brubank_pages import PAGES as BRUBANK_PAGES
from fixtures.galicia_pages import PAGES as GALICIA_PAGES
from moneytrail import categorize, db, reconcile
from moneytrail.ingest import import_parsed
from moneytrail.models import AccountInfo, Kind, Movement, ParsedStatement
from moneytrail.parsers.brubank_tarjeta import BrubankTarjetaParser
from moneytrail.parsers.galicia_caja_ahorro import GaliciaCajaAhorroParser

RULES = categorize.load_rules(Path(__file__).parent.parent / "rules" / "categories.yaml")


def _import_fixtures(conn):
    galicia = GaliciaCajaAhorroParser().parse(GALICIA_PAGES)[0]
    brubank = BrubankTarjetaParser().parse(BRUBANK_PAGES)[0]
    import_parsed(conn, galicia, "hash-galicia", "galicia.pdf")
    import_parsed(conn, brubank, "hash-brubank", "brubank.pdf")


def test_reimport_is_noop(conn):
    galicia = GaliciaCajaAhorroParser().parse(GALICIA_PAGES)[0]
    new1, _ = import_parsed(conn, galicia, "hash-1", "galicia.pdf")
    assert new1 == 6
    # Mismo contenido con otro hash de archivo (p. ej. extracto consolidado que
    # solapa el período): 0 movimientos nuevos.
    new2, dup2 = import_parsed(conn, galicia, "hash-2", "galicia_consolidado.pdf")
    assert (new2, dup2) == (0, 6)


def test_categorize_rules(conn):
    _import_fixtures(conn)
    updated = categorize.apply_rules(conn, RULES)
    assert updated > 0

    by_desc = {r["description"]: r for r in conn.execute("SELECT * FROM tx")}
    assert by_desc["TRANSFERENCIAS CASH"]["category"] == "Ingresos/Sueldo"
    assert by_desc["SNP PAGO A PROVEEDORES"]["category"] == "Ingresos/Reintegros"
    assert by_desc["Rappi"]["category"] == "Comida/Delivery"
    assert by_desc["Disney Plus"]["category"] == "Suscripciones"
    # Overrides de kind: los flujos internos dejan de ser 'expense'
    assert by_desc["TRANSF. CTAS PROPIAS"]["kind"] == "transfer_internal"
    assert by_desc["PAGO TARJETA VISA"]["kind"] == "card_payment"
    # La compra por débito se categoriza por la contraparte del detalle
    assert by_desc["COMPRA DEBITO 0783"]["category"] == "Transporte/Estacionamiento"


def test_rule_order_specific_wins(conn):
    stmt = ParsedStatement(
        account=AccountInfo(bank="X", product="caja_ahorro", currency="ARS", label="X CA"),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        movements=[
            Movement(
                date=date(2026, 5, 4),
                description="TRANSFERENCIA A TERCEROS",
                detail="Persona Cualquiera\nMERCADO LIBRE SRL",
                amount=Decimal("-1000"),
            )
        ],
    )
    import_parsed(conn, stmt, "hash-x", "x.pdf")
    categorize.apply_rules(conn, RULES)
    row = conn.execute("SELECT category FROM tx").fetchone()
    # 'MERCADO LIBRE' está antes que 'TRANSFERENCIA A TERCEROS' en las reglas
    assert row["category"] == "Compras/Mercado Libre"


def test_reconcile_card_payment(conn):
    _import_fixtures(conn)
    categorize.apply_rules(conn, RULES)
    # El PAGO TARJETA VISA de Galicia (-21.000, 20/04) no matchea los pagos
    # Brubank de junio (fechas lejanas): queda sin conciliar.
    result = reconcile.reconcile(conn)
    assert result.new_links == 0

    # Un pago de tarjeta compatible en fecha y monto sí se concilia.
    stmt = ParsedStatement(
        account=AccountInfo(bank="Otro", product="caja_ahorro", currency="ARS", label="Otro Banco CA"),
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        movements=[
            Movement(
                date=date(2026, 6, 2),
                description="PAGO TARJETA",
                amount=Decimal("-15000.00"),
                kind=Kind.CARD_PAYMENT,
            )
        ],
    )
    import_parsed(conn, stmt, "hash-otro", "otro.pdf")
    result = reconcile.reconcile(conn)
    assert result.new_links == 1
    link = conn.execute(
        """SELECT o.description AS o_desc, i.description AS i_desc, l.confidence
           FROM transfer_link l JOIN tx o ON o.id = l.tx_out_id JOIN tx i ON i.id = l.tx_in_id"""
    ).fetchone()
    assert link["o_desc"] == "PAGO TARJETA"
    assert link["i_desc"] == "Pago recibido"
    assert link["confidence"] > 0.5
    # Re-conciliar es idempotente
    assert reconcile.reconcile(conn).new_links == 0


def test_uncategorized_review(conn):
    _import_fixtures(conn)
    categorize.apply_rules(conn, RULES)
    pending = categorize.uncategorized_summary(conn)
    # 'Lentesfx' no está en la fixture; lo que quede pendiente no debe incluir internos
    assert all("TRANSF" not in p["description"] for p in pending)
