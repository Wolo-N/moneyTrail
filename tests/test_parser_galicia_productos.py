"""Galicia usa el mismo layout para todos sus productos de cuenta.

El parser detecta por estructura, no por el nombre del producto: así una
cuenta corriente —o cualquier producto nuevo— entra sola, sin necesidad de
escribir un parser por cada título distinto.
"""

from decimal import Decimal

from fixtures.galicia_cuenta_corriente_pages import PAGES, PAGES_WITH_MOVEMENTS
from fixtures.galicia_pages import PAGES as CAJA_AHORRO_PAGES
from moneytrail.parsers import find_parser
from moneytrail.parsers.galicia_caja_ahorro import GaliciaCajaAhorroParser


def test_cuenta_corriente_is_recognized():
    parser = find_parser(PAGES)
    assert parser is not None and parser.name == "galicia_caja_ahorro"


def test_empty_statement_parses_without_movements():
    """Una cuenta sin uso llega con 'Sin Movimientos' y debe entrar igual."""
    stmt = GaliciaCajaAhorroParser().parse(PAGES)[0]
    assert stmt.movements == []
    assert stmt.opening_balance == Decimal("0.00")
    assert stmt.closing_balance == Decimal("0.00")


def test_account_label_follows_the_product():
    stmt = GaliciaCajaAhorroParser().parse(PAGES)[0]
    assert stmt.account.label == "Galicia Cuenta Corriente"
    assert stmt.account.product == "cuenta_corriente"
    assert stmt.account.currency == "ARS"


def test_caja_de_ahorro_keeps_its_historical_label():
    """Si la etiqueta cambiara, el histórico ya importado se partiría en dos
    cuentas distintas."""
    stmt = GaliciaCajaAhorroParser().parse(CAJA_AHORRO_PAGES)[0]
    assert stmt.account.label == "Galicia Caja de Ahorro"


def test_cuenta_corriente_with_movements():
    stmt = GaliciaCajaAhorroParser().parse(PAGES_WITH_MOVEMENTS)[0]
    assert len(stmt.movements) == 1
    mv = stmt.movements[0]
    assert mv.amount == Decimal("-15000.00")
    assert mv.counterparty == "PROVEEDOR EJEMPLO"
    assert stmt.account.label == "Galicia Cuenta Corriente"


def test_dollar_account_gets_its_currency():
    pages = [PAGES[0].replace("en Pesos", "en Dólares")]
    stmt = GaliciaCajaAhorroParser().parse(pages)[0]
    assert stmt.account.currency == "USD"
    assert stmt.account.label == "Galicia Cuenta Corriente"


def test_other_banks_are_not_swallowed():
    """La detección por estructura no debe robarle documentos a otros parsers."""
    from fixtures.amex_pages import PAGES as AMEX
    from fixtures.brubank_cuenta_pages import PAGES as BRUBANK_CUENTA
    from fixtures.brubank_pages import PAGES as BRUBANK_TARJETA
    from fixtures.galicia_visa_pages import PAGES as VISA

    assert find_parser(AMEX).name == "amex_tarjeta"
    assert find_parser(BRUBANK_CUENTA).name == "brubank_cuenta"
    assert find_parser(BRUBANK_TARJETA).name == "brubank_tarjeta"
    assert find_parser(VISA).name == "galicia_visa"
