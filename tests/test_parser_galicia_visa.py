from datetime import date
from decimal import Decimal

import pytest

from fixtures.galicia_visa_pages import PAGES, WORDS, ars
from moneytrail.models import Kind, ParseError
from moneytrail.parsers import find_parser
from moneytrail.parsers.galicia_visa import GaliciaVisaParser


def _parse(pages=None, words=None):
    return GaliciaVisaParser().parse_words(pages or PAGES, words or WORDS)[0]


def test_detect():
    parser = find_parser(PAGES)
    assert parser is not None and parser.name == "galicia_visa"


def test_detect_does_not_steal_caja_de_ahorro():
    """El otro resumen de Galicia (caja de ahorro) tiene su propio parser."""
    from fixtures.galicia_pages import PAGES as CA_PAGES

    assert find_parser(CA_PAGES).name == "galicia_caja_ahorro"


def test_period_from_billing_cycle():
    stmt = _parse()
    # Cierre anterior → cierre actual, no las fechas de los consumos
    assert stmt.period_start == date(2026, 7, 2)
    assert stmt.period_end == date(2026, 7, 30)


def test_balances():
    stmt = _parse()
    assert stmt.opening_balance == Decimal("100000.00")
    assert stmt.closing_balance == Decimal("66000.00")


def test_payment_is_a_credit():
    stmt = _parse()
    pago = next(m for m in stmt.movements if m.kind == Kind.CARD_PAYMENT)
    assert pago.date == date(2026, 7, 7)
    assert pago.amount == Decimal("100000.00"), "el pago llega con signo negativo y es un crédito"


def test_consumptions_assigned_to_their_card():
    stmt = _parse()
    consumos = [m for m in stmt.movements if m.kind == Kind.EXPENSE]
    assert len(consumos) == 4
    por_tarjeta = {}
    for m in consumos:
        por_tarjeta.setdefault(m.detail, []).append(m.description)
    assert por_tarjeta["Tarjeta 9796"] == ["JUMBO PACHECO", "KFC Ruta 202"]
    assert por_tarjeta["Tarjeta 0905"] == ["ZULU HAUS", "SERVICIO EXTERIOR"]


def test_merchant_name_keeps_its_own_digits():
    """'KFC Ruta 202' conserva el 202; el 854027 es el comprobante."""
    stmt = _parse()
    kfc = next(m for m in stmt.movements if m.description.startswith("KFC"))
    assert kfc.description == "KFC Ruta 202"
    assert kfc.ref == "854027"


def test_dollar_column_is_read_as_dollars():
    """La única señal de que un consumo es en dólares es su posición."""
    stmt = _parse()
    exterior = next(m for m in stmt.movements if m.description == "SERVICIO EXTERIOR")
    assert exterior.currency == "USD"
    assert exterior.amount == Decimal("-25.50")
    assert all(m.currency == "ARS" for m in stmt.movements if m.description != "SERVICIO EXTERIOR")


def test_tax_row():
    stmt = _parse()
    impuesto = next(m for m in stmt.movements if m.kind == Kind.TAX)
    assert impuesto.description == "IMPUESTO DE SELLOS", "el '$' no es parte del nombre"
    assert impuesto.amount == Decimal("-1000.00")


def test_card_subtotal_validation():
    """Si se pierde un consumo, el subtotal de esa tarjeta deja de cerrar."""
    words = [[w for w in WORDS[0] if w["text"] != "20.000,00"]]
    with pytest.raises(ParseError, match="tarjeta 9796"):
        _parse(words=words)


def test_total_validation():
    corrupt = []
    for w in WORDS[0]:
        w = dict(w)
        if w["text"] == "66.000,00":
            w["text"] = "77.000,00"
        corrupt.append(w)
    with pytest.raises(ParseError, match="total a pagar no cierra"):
        _parse(words=[corrupt])


def test_no_movements_raises():
    with pytest.raises(ParseError, match="no se encontraron movimientos"):
        GaliciaVisaParser().parse_words(PAGES, [[]])


def test_parse_without_words_is_explicit():
    """El contrato de texto plano no alcanza para este formato."""
    with pytest.raises(ParseError, match="coordenadas"):
        GaliciaVisaParser().parse(PAGES)


def test_helpers_place_amounts_in_the_right_column():
    assert ars("1,00")[2] == 494
