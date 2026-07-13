from datetime import date
from decimal import Decimal

import pytest

from fixtures.brubank_pages import PAGES
from moneytrail.models import Kind, ParseError
from moneytrail.parsers import find_parser
from moneytrail.parsers.brubank_tarjeta import BrubankTarjetaParser


def test_detect():
    parser = find_parser(PAGES)
    assert parser is not None and parser.name == "brubank_tarjeta"


def test_consumptions():
    stmt = BrubankTarjetaParser().parse(PAGES)
    consumos = [m for m in stmt.movements if m.kind == Kind.EXPENSE]
    assert len(consumos) == 3
    rappi = consumos[0]
    assert (rappi.date, rappi.amount, rappi.currency) == (date(2026, 6, 1), Decimal("-20000.00"), "ARS")
    assert rappi.ref == "1000000001"
    assert rappi.detail == "Tarjeta 1111"
    claude = consumos[1]
    assert (claude.description, claude.amount, claude.currency) == (
        "Anthropic* Claude Sub",
        Decimal("-20.00"),
        "USD",
    )


def test_fees_taxes_and_payments():
    stmt = BrubankTarjetaParser().parse(PAGES)
    fees = [m for m in stmt.movements if m.kind == Kind.FEE]
    assert len(fees) == 1 and fees[0].amount == Decimal("-1000.00")

    taxes = [m for m in stmt.movements if m.kind == Kind.TAX]
    assert len(taxes) == 1 and taxes[0].description == "IVA" and taxes[0].amount == Decimal("-210.00")

    pagos = [m for m in stmt.movements if m.kind == Kind.CARD_PAYMENT]
    assert [(p.amount, p.currency) for p in pagos] == [
        (Decimal("15000.00"), "ARS"),
        (Decimal("6000.00"), "ARS"),
        (Decimal("5.00"), "USD"),
    ]


def test_period_from_movements():
    stmt = BrubankTarjetaParser().parse(PAGES)
    assert stmt.period_start == date(2026, 6, 1)
    assert stmt.period_end == date(2026, 6, 16)


def test_subtotal_validation():
    corrupt = [p.replace("2026-06-10 1000000003 Disney Plus $ 10.000,00", "") for p in PAGES]
    with pytest.raises(ParseError, match="subtotal tarjeta 1111"):
        BrubankTarjetaParser().parse(corrupt)


def test_payments_total_validation():
    corrupt = [p.replace("2026-06-16 $ 6.000,00", "") for p in PAGES]
    with pytest.raises(ParseError, match="pagos ARS"):
        BrubankTarjetaParser().parse(corrupt)
