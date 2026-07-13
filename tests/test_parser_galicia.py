from datetime import date
from decimal import Decimal

import pytest

from fixtures.galicia_pages import PAGES
from moneytrail.models import ParseError
from moneytrail.parsers import find_parser
from moneytrail.parsers.galicia_caja_ahorro import GaliciaCajaAhorroParser


def test_detect():
    parser = find_parser(PAGES)
    assert parser is not None and parser.name == "galicia_caja_ahorro"


def test_parse_header():
    stmt = GaliciaCajaAhorroParser().parse(PAGES)[0]
    assert stmt.period_start == date(2026, 4, 1)
    assert stmt.period_end == date(2026, 4, 30)
    assert stmt.opening_balance == Decimal("100000.00")
    assert stmt.closing_balance == Decimal("150006.67")
    assert stmt.account.bank == "Banco Galicia"


def test_parse_movements():
    stmt = GaliciaCajaAhorroParser().parse(PAGES)[0]
    assert len(stmt.movements) == 6

    reintegro = stmt.movements[0]
    assert reintegro.date == date(2026, 4, 5)
    assert reintegro.amount == Decimal("80000.00")
    assert reintegro.counterparty == "EMPRESA EJEMPLO"
    assert "CITIBANK N.A." in reintegro.detail

    debito = stmt.movements[1]
    assert debito.amount == Decimal("-21000.00")
    assert debito.counterparty == "PLAYAS SUBTERRANEAS"

    transf = stmt.movements[2]
    assert transf.description == "TRANSF. CTAS PROPIAS"
    assert transf.counterparty == "BBNK"  # saltea 'CU <cuil>' y líneas numéricas

    interes = stmt.movements[3]  # monto sin separador de miles, cruza de página
    assert interes.amount == Decimal("6.67")

    sueldo = stmt.movements[4]
    assert sueldo.amount == Decimal("62000.00")
    assert "SUELDOS" in sueldo.detail


def test_running_balance_validation():
    corrupt = [p.replace("80.000,00 180.000,00", "80.000,00 181.000,00") for p in PAGES]
    with pytest.raises(ParseError, match="saldo corrido"):
        GaliciaCajaAhorroParser().parse(corrupt)


def test_missing_movement_detected():
    # Sacar una fila completa (crédito de 80.000) rompe el saldo corrido siguiente
    lines = PAGES[0].splitlines()
    del lines[16:20]
    with pytest.raises(ParseError):
        GaliciaCajaAhorroParser().parse(["\n".join(lines), PAGES[1]])
