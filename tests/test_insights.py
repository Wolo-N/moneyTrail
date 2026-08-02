from datetime import date
from decimal import Decimal

import pytest

from moneytrail.ingest import import_parsed
from moneytrail.insights import build_insights, merchant_key
from moneytrail.models import AccountInfo, Kind, Movement, ParsedStatement


@pytest.mark.parametrize(
    ("description", "counterparty", "expected"),
    [
        # Los números de referencia cambian en cada compra: no son el comercio
        ("RAPPI 624875624875", "", "RAPPI"),
        ("RAPPI 707314707314", "", "RAPPI"),
        ("PARKING DE LAS ARTES 16482918 00:0", "", "PARKING DE LAS ARTES"),
        ("PAYU-UBER 828987 4661812622", "", "PAYU-UBER"),
        # Brubank mete el CUIT adelante del nombre
        ("20461735283 - Juan Perez", "", "JUAN PEREZ"),
        # Galicia pone el comercio en la contraparte, no en la descripción
        ("COMPRA DEBITO 0783", "PLAYAS SUBTERRANEAS", "PLAYAS SUBTERRANEAS"),
        # Mayúsculas/minúsculas no deberían partir un comercio en dos
        ("Rappi", "", "RAPPI"),
        ("", "", "(sin descripción)"),
    ],
)
def test_merchant_key(description, counterparty, expected):
    assert merchant_key(description, counterparty) == expected


def _stmt(label, movements, currency="ARS"):
    return ParsedStatement(
        account=AccountInfo(bank="Test", product="caja_ahorro", currency=currency, label=label),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        movements=movements,
    )


def _mv(day, desc, amount, kind=Kind.EXPENSE, currency="ARS", counterparty=""):
    return Movement(
        date=date.fromisoformat(day), description=desc, amount=Decimal(str(amount)),
        currency=currency, kind=kind, counterparty=counterparty,
    )


@pytest.fixture
def seeded(conn):
    """Tres meses de datos con sueldo, delivery mensual y una compra grande."""
    movements = [
        _mv("2026-04-01", "SUELDO", 1000, Kind.INCOME),
        _mv("2026-04-05", "RAPPI 111111111111", -100),
        _mv("2026-04-20", "NETFLIX", -50),
        _mv("2026-05-01", "SUELDO", 1000, Kind.INCOME),
        _mv("2026-05-05", "RAPPI 222222222222", -200),
        _mv("2026-05-20", "NETFLIX", -50),
        _mv("2026-06-01", "SUELDO", 1200, Kind.INCOME),
        _mv("2026-06-05", "RAPPI 333333333333", -300),
        _mv("2026-06-20", "NETFLIX", -60),
        _mv("2026-06-25", "HELADERA", -900),
    ]
    import_parsed(conn, _stmt("Cuenta Test", movements), "h1", "t.pdf")
    conn.execute("UPDATE tx SET category = 'Comida/Delivery' WHERE description LIKE 'RAPPI%'")
    conn.execute("UPDATE tx SET category = 'Suscripciones' WHERE description = 'NETFLIX'")
    conn.execute("UPDATE tx SET category = 'Hogar' WHERE description = 'HELADERA'")
    conn.execute("UPDATE tx SET category = 'Ingresos/Sueldo' WHERE description = 'SUELDO'")
    conn.commit()
    return conn


def test_totals_and_savings_rate(seeded):
    ins = build_insights(seeded, "2026-06-01", "2026-06-30")
    assert ins["totals"]["income"] == 1200
    assert ins["totals"]["expense"] == 1260  # 300 + 60 + 900
    assert ins["totals"]["savings"] == -60
    assert ins["totals"]["savings_rate"] == -5.0
    assert ins["totals"]["n_transactions"] == 4


def test_monthly_series_covers_all_history(seeded):
    ins = build_insights(seeded, "2026-06-01", "2026-06-30")
    # La serie mensual ignora el período elegido: es la tendencia completa
    assert [m["month"] for m in ins["monthly"]] == ["2026-04", "2026-05", "2026-06"]
    assert [m["expense"] for m in ins["monthly"]] == [150, 250, 1260]
    assert ins["monthly"][0]["savings"] == 850


def test_monthly_series_fills_empty_months(conn):
    import_parsed(
        conn,
        _stmt("C", [_mv("2026-01-10", "A", -100), _mv("2026-04-10", "B", -100)]),
        "h",
        "t.pdf",
    )
    ins = build_insights(conn)
    # Febrero y marzo sin movimientos deben aparecer en cero, no desaparecer
    assert [m["month"] for m in ins["monthly"]] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert ins["monthly"][1]["expense"] == 0


def test_categories_ranked_with_share(seeded):
    ins = build_insights(seeded, "2026-06-01", "2026-06-30")
    cats = ins["categories"]
    assert cats[0]["category"] == "Hogar" and cats[0]["total"] == 900
    assert round(cats[0]["share"]) == 71  # 900 de 1260
    assert sum(c["total"] for c in cats) == ins["totals"]["expense"]


def test_month_over_month(seeded):
    ins = build_insights(seeded, "2026-06-01", "2026-06-30")
    mom = ins["category_mom"]
    assert mom["current_month"] == "2026-06" and mom["previous_month"] == "2026-05"
    delivery = next(r for r in mom["rows"] if r["category"] == "Comida/Delivery")
    assert delivery["previous"] == 200 and delivery["current"] == 300
    assert delivery["delta"] == 100 and delivery["delta_pct"] == 50.0
    # Hogar es nuevo este mes: sin base de comparación
    hogar = next(r for r in mom["rows"] if r["category"] == "Hogar")
    assert hogar["previous"] == 0 and hogar["delta_pct"] is None


def test_recurring_detects_subscription_and_increase(seeded):
    ins = build_insights(seeded)
    rec = {r["merchant"]: r for r in ins["recurring"]}
    assert "NETFLIX" in rec, "3 meses seguidos: es recurrente"
    assert rec["NETFLIX"]["months"] == 3
    assert rec["NETFLIX"]["kind"] == "fijo", "50/50/60 es prácticamente el mismo importe"
    assert rec["NETFLIX"]["change_pct"] == 20.0  # 50 → 60: el aumento silencioso
    # Rappi agrupa pese a los números de referencia distintos, pero 100/200/300
    # no es un cargo fijo: es un hábito
    assert rec["RAPPI"]["months"] == 3
    assert rec["RAPPI"]["kind"] == "variable"
    assert rec["RAPPI"]["change_pct"] is None, "comparar dos compras variables no dice nada"
    assert rec["RAPPI"]["monthly_cost"] == 200  # 600 en 3 meses
    # Una compra única no es recurrente
    assert "HELADERA" not in rec


def test_recurring_needs_two_distinct_months(conn):
    """Dos compras en el mismo mes no son un gasto recurrente."""
    movements = [
        _mv("2026-06-01", "GIMNASIO", -100),
        _mv("2026-06-20", "GIMNASIO", -100),
        _mv("2026-06-02", "DIARIO", -50),
        _mv("2026-07-02", "DIARIO", -50),
    ]
    import_parsed(conn, _stmt("C", movements), "h", "t.pdf")
    rec = {r["merchant"]: r for r in build_insights(conn)["recurring"]}
    assert "GIMNASIO" not in rec
    assert rec["DIARIO"]["kind"] == "fijo"


def test_merchants_grouped_and_ranked(seeded):
    ins = build_insights(seeded)
    merchants = {m["merchant"]: m for m in ins["merchants"]}
    assert merchants["RAPPI"]["n"] == 3
    assert merchants["RAPPI"]["total"] == 600
    assert merchants["RAPPI"]["category"] == "Comida/Delivery"
    assert ins["merchants"][0]["merchant"] == "HELADERA"  # el más caro primero


def test_usd_converted_at_given_rate(conn):
    import_parsed(
        conn,
        _stmt("USD", [_mv("2026-06-01", "ANTHROPIC", -20, currency="USD")], currency="USD"),
        "h",
        "t.pdf",
    )
    ins = build_insights(conn, usd_rate=Decimal(1400))
    assert ins["totals"]["expense"] == 28000


def test_biggest_expenses_sorted(seeded):
    ins = build_insights(seeded)
    assert ins["biggest"][0]["description"] == "HELADERA"
    assert ins["biggest"][0]["amount"] == 900


def test_internal_flows_never_count(conn):
    movements = [
        _mv("2026-06-01", "SUELDO", 1000, Kind.INCOME),
        _mv("2026-06-02", "TRANSF. CTAS PROPIAS", -500, Kind.TRANSFER_INTERNAL),
        _mv("2026-06-03", "PAGO TARJETA", -300, Kind.CARD_PAYMENT),
    ]
    import_parsed(conn, _stmt("C", movements), "h", "t.pdf")
    ins = build_insights(conn)
    assert ins["totals"]["expense"] == 0, "mover plata entre cuentas propias no es gasto"
    assert ins["totals"]["income"] == 1000
