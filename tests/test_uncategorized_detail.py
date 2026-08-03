"""Al categorizar hace falta saber de dónde salió la plata y cuándo."""

from datetime import date
from decimal import Decimal

from moneytrail.categorize import uncategorized_summary
from moneytrail.ingest import import_parsed
from moneytrail.models import AccountInfo, Kind, Movement, ParsedStatement


def _stmt(label, movements):
    return ParsedStatement(
        account=AccountInfo(bank="T", product="tarjeta_credito", currency="ARS", label=label),
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        movements=movements,
    )


def _mv(day, desc, amount, detail="", kind=Kind.EXPENSE):
    return Movement(date=date.fromisoformat(day), description=desc,
                    amount=Decimal(str(amount)), detail=detail, kind=kind)


def test_group_carries_accounts_dates_and_movements(conn):
    movements = [
        _mv("2026-06-03", "COMERCIO X", -1000),
        _mv("2026-06-20", "COMERCIO X", -2500),
    ]
    import_parsed(conn, _stmt("Brubank Tarjeta", movements), "h", "t.pdf")
    group = uncategorized_summary(conn)[0]
    assert group["n"] == 2
    assert group["approx_total"] == -3500
    assert group["accounts"] == ["Brubank Tarjeta"]
    assert group["first_date"] == "2026-06-03" and group["last_date"] == "2026-06-20"
    assert [m["date"] for m in group["movements"]] == ["2026-06-20", "2026-06-03"]
    assert all(m["account"] == "Brubank Tarjeta" for m in group["movements"])


def test_card_number_shown_when_the_statement_distinguishes_it(conn):
    movements = [_mv("2026-06-03", "COMERCIO X", -1000, detail="Tarjeta 9796")]
    import_parsed(conn, _stmt("Galicia Tarjeta VISA", movements), "h", "t.pdf")
    group = uncategorized_summary(conn)[0]
    assert group["accounts"] == ["Galicia Tarjeta VISA · Tarjeta 9796"]


def test_bank_detail_is_not_shown_as_a_card(conn):
    """En los resúmenes bancarios 'detail' trae CBU y CUIT, no una tarjeta."""
    movements = [_mv("2026-06-03", "DEBITO DEBIN", -1000, detail="28504616300011854610\n30574816870\nVARIOS")]
    import_parsed(conn, _stmt("Galicia Caja de Ahorro", movements), "h", "t.pdf")
    group = uncategorized_summary(conn)[0]
    assert group["accounts"] == ["Galicia Caja de Ahorro"]


def test_same_merchant_across_two_accounts(conn):
    """El mismo comercio pagado con dos tarjetas distintas lista las dos."""
    import_parsed(conn, _stmt("Tarjeta A", [_mv("2026-06-03", "COMERCIO X", -1000)]), "h1", "a.pdf")
    import_parsed(conn, _stmt("Tarjeta B", [_mv("2026-06-05", "COMERCIO X", -1000)]), "h2", "b.pdf")
    group = uncategorized_summary(conn)[0]
    assert sorted(group["accounts"]) == ["Tarjeta A", "Tarjeta B"]
    assert group["n"] == 2


def test_detail_list_is_capped(conn):
    movements = [_mv("2026-06-%02d" % (d + 1), "COMERCIO X", -100) for d in range(20)]
    import_parsed(conn, _stmt("Tarjeta", movements), "h", "t.pdf")
    group = uncategorized_summary(conn, detail_limit=5)[0]
    assert group["n"] == 20, "el conteo es del total"
    assert len(group["movements"]) == 5, "el detalle se corta para no inflar la respuesta"


def test_internal_flows_stay_out(conn):
    movements = [
        _mv("2026-06-03", "PAGO TARJETA", -1000, kind=Kind.CARD_PAYMENT),
        _mv("2026-06-04", "COMERCIO X", -500),
    ]
    import_parsed(conn, _stmt("Tarjeta", movements), "h", "t.pdf")
    assert [g["description"] for g in uncategorized_summary(conn)] == ["COMERCIO X"]
