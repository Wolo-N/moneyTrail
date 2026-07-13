from decimal import Decimal, InvalidOperation

import pytest

from moneytrail.models import parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("-21.000,00", Decimal("-21000.00")),
        ("6,67", Decimal("6.67")),
        ("$ 12.809,92", Decimal("12809.92")),
        ("U$S 34,95", Decimal("34.95")),
        ("2.695.815,00", Decimal("2695815.00")),
        ("0", Decimal("0")),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "12.34,56.78", "1,234.56", ""])
def test_parse_amount_rejects_garbage(raw):
    with pytest.raises(InvalidOperation):
        parse_amount(raw)
