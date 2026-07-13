from datetime import date
from decimal import Decimal

import pytest

from fixtures.brubank_cuenta_pages import PAGES
from moneytrail.models import ParseError
from moneytrail.parsers import find_parser
from moneytrail.parsers.brubank_cuenta import BrubankCuentaParser


def test_detect():
    parser = find_parser(PAGES)
    assert parser is not None and parser.name == "brubank_cuenta"


def test_empty_subaccount_is_skipped():
    # El documento trae 3 bloques ('Mi cuenta Resumen'); 'Cuenta remunerada'
    # no tiene movimientos y no debería generar un ParsedStatement.
    stmts = BrubankCuentaParser().parse(PAGES)
    assert len(stmts) == 2
    assert all(s.movements for s in stmts)


def test_ars_block_spans_pages():
    stmts = BrubankCuentaParser().parse(PAGES)
    ars = next(s for s in stmts if s.account.currency == "ARS")
    assert ars.account.label == "Brubank Caja de ahorro (ARS)"
    assert ars.opening_balance == Decimal("100000.00")
    assert ars.closing_balance == Decimal("120000.00")
    # La 3ra fila viene de la página 2, continuación de la misma tabla
    assert len(ars.movements) == 3

    transferencia = ars.movements[0]
    assert transferencia.date == date(2026, 6, 1)
    assert transferencia.description == "A una cuenta tuya - Galicia"
    assert transferencia.amount == Decimal("-20000.00")
    assert transferencia.ref == "2000000001"

    con_guion_interno = ars.movements[1]
    assert con_guion_interno.description == "20461735283 - Juan Perez"  # guion propio de la descripción
    assert con_guion_interno.amount == Decimal("50000.00")

    pago_tarjeta = ars.movements[2]
    assert pago_tarjeta.date == date(2026, 6, 5)
    assert pago_tarjeta.amount == Decimal("-10000.00")


def test_usd_block():
    stmts = BrubankCuentaParser().parse(PAGES)
    usd = next(s for s in stmts if s.account.currency == "USD")
    assert usd.account.label == "Brubank Caja de ahorro (USD)"
    assert usd.opening_balance == Decimal("10.00")
    assert usd.closing_balance == Decimal("25.00")
    assert [(m.description, m.amount) for m in usd.movements] == [
        ("De una cuenta tuya - Galicia", Decimal("20.00")),
        ("Pago de tarjeta de crédito", Decimal("-5.00")),
    ]


def test_running_balance_validation():
    corrupt = [PAGES[0].replace("$ 80.000,00", "$ 81.000,00"), PAGES[1]]
    with pytest.raises(ParseError, match="saldo corrido"):
        BrubankCuentaParser().parse(corrupt)


def test_totals_validation():
    corrupt = [PAGES[0].replace("Créditos $ 50.000,00", "Créditos $ 99.000,00"), PAGES[1]]
    with pytest.raises(ParseError, match="totales no cierran"):
        BrubankCuentaParser().parse(corrupt)
