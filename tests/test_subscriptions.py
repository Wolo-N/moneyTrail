"""El panel de suscripciones: qué se paga todos los meses."""

from datetime import date
from decimal import Decimal

from moneytrail.ingest import import_parsed
from moneytrail.insights import build_insights
from moneytrail.models import AccountInfo, Kind, Movement, ParsedStatement


def _stmt(label, movements, start="2026-04-01", end="2026-06-30"):
    return ParsedStatement(
        account=AccountInfo(bank="T", product="tarjeta_credito", currency="ARS", label=label),
        period_start=date.fromisoformat(start),
        period_end=date.fromisoformat(end),
        movements=movements,
    )


def _mv(day, desc, amount, currency="ARS", kind=Kind.EXPENSE):
    return Movement(date=date.fromisoformat(day), description=desc,
                    amount=Decimal(str(amount)), currency=currency, kind=kind)


def test_known_service_detected_from_a_single_charge(conn):
    """Con un solo resumen importado, Disney+ aparece una vez y sigue siendo
    una suscripción: exigir varios meses la escondería justo al principio."""
    import_parsed(conn, _stmt("Tarjeta", [_mv("2026-06-18", "Disney Plus", -11999)]), "h", "t.pdf")
    subs = build_insights(conn)["subscriptions"]
    assert [s["merchant"] for s in subs] == ["DISNEY PLUS"]
    assert subs[0]["monthly_cost"] == 11999
    assert subs[0]["yearly_cost"] == 11999 * 12
    assert subs[0]["active"] is True


def test_price_increase_is_visible(conn):
    movements = [
        _mv("2026-04-18", "Paramount Plus", -5000),
        _mv("2026-05-18", "Paramount Plus", -5000),
        _mv("2026-06-18", "Paramount Plus", -6500),
    ]
    import_parsed(conn, _stmt("Tarjeta", movements), "h", "t.pdf")
    sub = build_insights(conn)["subscriptions"][0]
    assert sub["months"] == 3
    assert sub["change_pct"] == 30.0  # 5000 → 6500
    assert sub["last_amount"] == 6500


def test_dollar_subscription_converted_for_the_monthly_total(conn):
    import_parsed(
        conn,
        _stmt("Tarjeta", [_mv("2026-06-03", "Anthropic* Claude Sub", -20, currency="USD")]),
        "h",
        "t.pdf",
    )
    sub = build_insights(conn, usd_rate=Decimal(1400))["subscriptions"][0]
    assert sub["currency"] == "USD"
    assert sub["last_amount"] == 20, "el importe se muestra en su moneda"
    assert sub["monthly_cost"] == 28000, "el costo mensual se compara en pesos"


def test_inactive_subscription_flagged(conn):
    """Sin cargos en el último mes y medio: puede estar dada de baja."""
    movements = [
        _mv("2026-04-10", "Netflix", -8000),
        _mv("2026-05-10", "Netflix", -8000),
        _mv("2026-06-25", "Spotify", -5000),
    ]
    import_parsed(conn, _stmt("Tarjeta", movements), "h", "t.pdf")
    subs = {s["merchant"]: s for s in build_insights(conn)["subscriptions"]}
    assert subs["SPOTIFY"]["active"] is True
    assert subs["NETFLIX"]["active"] is False
    # Las activas van primero, para que lo vigente quede arriba
    assert build_insights(conn)["subscriptions"][0]["merchant"] == "SPOTIFY"


def test_variable_habit_is_not_a_subscription(conn):
    movements = [
        _mv("2026-04-05", "RAPPI 111", -10000),
        _mv("2026-05-05", "RAPPI 222", -25000),
        _mv("2026-06-05", "RAPPI 333", -40000),
    ]
    import_parsed(conn, _stmt("Tarjeta", movements), "h", "t.pdf")
    ins = build_insights(conn)
    assert ins["subscriptions"] == []
    assert [r["merchant"] for r in ins["recurring"]] == ["RAPPI"]


def test_fixed_recurring_charge_counts_even_if_unknown(conn):
    """Un abono que no está en la lista de servicios conocidos igual entra si
    se cobra fijo todos los meses."""
    movements = [
        _mv("2026-04-01", "COCHERA EDIFICIO", -30000),
        _mv("2026-05-01", "COCHERA EDIFICIO", -30000),
        _mv("2026-06-01", "COCHERA EDIFICIO", -30000),
    ]
    import_parsed(conn, _stmt("Tarjeta", movements), "h", "t.pdf")
    subs = build_insights(conn)["subscriptions"]
    assert [s["merchant"] for s in subs] == ["COCHERA EDIFICIO"]
    assert subs[0]["monthly_cost"] == 30000


def test_user_category_makes_it_a_subscription(conn):
    import_parsed(conn, _stmt("Tarjeta", [_mv("2026-06-10", "SERVICIO RARO", -1000)]), "h", "t.pdf")
    conn.execute("UPDATE tx SET category = 'Suscripciones/Varios'")
    conn.commit()
    subs = build_insights(conn)["subscriptions"]
    assert [s["merchant"] for s in subs] == ["SERVICIO RARO"]
    assert subs[0]["category"] == "Suscripciones/Varios"
