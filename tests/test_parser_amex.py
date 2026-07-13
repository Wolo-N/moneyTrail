from datetime import date
from decimal import Decimal

import pytest

from fixtures.amex_pages import PAGES
from moneytrail.models import Kind, ParseError
from moneytrail.parsers import find_parser
from moneytrail.parsers.amex_tarjeta import AmexTarjetaParser


def test_detect():
    parser = find_parser(PAGES)
    assert parser is not None and parser.name == "amex_tarjeta"


def test_parse_movements():
    stmt = AmexTarjetaParser().parse(PAGES)[0]
    assert stmt.account.bank == "American Express"
    assert len(stmt.movements) == 3

    pago = stmt.movements[0]
    assert pago.kind == Kind.CARD_PAYMENT
    assert pago.amount == Decimal("100000.00")
    assert pago.description == "Gracias por su pago realizado en Banco Ejemplo S.A."

    # Monto con el espacio errático de extracción ('20 .000,00') resuelto bien
    rappi = stmt.movements[1]
    assert rappi.kind == Kind.EXPENSE
    assert rappi.amount == Decimal("-20000.00")
    assert rappi.description == "RAPPI 111111111111"

    parking = stmt.movements[2]
    assert parking.amount == Decimal("-30000.00")
    assert parking.date == date(2026, 6, 17)


def test_totals_validation():
    corrupt = [PAGES[0].replace("17 de Junio PARKING DE LAS ARTES 16482918 00:0 30.000,00", ""), PAGES[1]]
    with pytest.raises(ParseError, match="total de cargos en ARS"):
        AmexTarjetaParser().parse(corrupt)


def test_december_billed_in_january_previous_year():
    # Si la facturación es de enero y un consumo dice 'diciembre', es del
    # año calendario anterior (no del mismo año que la facturación).
    december_page = PAGES[0].replace(
        "03 de Junio RAPPI 111111111111 20 .000,00", "03 de Diciembre RAPPI 111111111111 20.000,00"
    ).replace("05/07/26 14/07/26", "05/01/27 14/01/27")
    stmt = AmexTarjetaParser().parse([december_page, PAGES[1]])[0]
    diciembre_mv = next(m for m in stmt.movements if "RAPPI 111111111111" in m.description)
    assert diciembre_mv.date == date(2026, 12, 3)
