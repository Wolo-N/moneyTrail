"""Meses incompletos: si falta un extracto, el mes no se puede comparar."""

from datetime import date
from decimal import Decimal

from moneytrail.ingest import import_parsed
from moneytrail.insights import build_insights, month_coverage
from moneytrail.models import AccountInfo, Kind, Movement, ParsedStatement


def _stmt(label, start, end, movements):
    return ParsedStatement(
        account=AccountInfo(bank="T", product="caja_ahorro", currency="ARS", label=label),
        period_start=date.fromisoformat(start),
        period_end=date.fromisoformat(end),
        movements=movements,
    )


def _mv(day, desc, amount, kind=Kind.EXPENSE):
    return Movement(date=date.fromisoformat(day), description=desc, amount=Decimal(str(amount)), kind=kind)


def test_single_account_always_complete(conn):
    import_parsed(conn, _stmt("A", "2026-05-01", "2026-06-30", [_mv("2026-05-02", "x", -1)]), "h", "f.pdf")
    assert month_coverage(conn) == {"2026-05": True, "2026-06": True}


def test_month_missing_one_account_is_incomplete(conn):
    import_parsed(conn, _stmt("Banco", "2026-05-01", "2026-06-30", [_mv("2026-05-02", "x", -1)]), "h1", "a.pdf")
    import_parsed(conn, _stmt("Tarjeta", "2026-05-01", "2026-05-31", [_mv("2026-05-03", "y", -1)]), "h2", "b.pdf")
    cov = month_coverage(conn)
    assert cov["2026-05"] is True
    assert cov["2026-06"] is False, "en junio falta el resumen de la tarjeta"


def test_incomplete_month_flagged_in_series(conn):
    """El mes sin el extracto del sueldo no debe leerse como un mes malo."""
    sueldo = [_mv("2026-05-10", "SUELDO", 1000, Kind.INCOME)]
    import_parsed(conn, _stmt("Banco", "2026-05-01", "2026-05-31", sueldo), "h1", "a.pdf")
    gastos = [_mv("2026-05-15", "compra", -100), _mv("2026-06-15", "compra", -300)]
    import_parsed(conn, _stmt("Tarjeta", "2026-05-01", "2026-06-30", gastos), "h2", "b.pdf")

    monthly = {m["month"]: m for m in build_insights(conn)["monthly"]}
    assert monthly["2026-05"]["complete"] is True
    assert monthly["2026-06"]["complete"] is False
    # Junio da -300 sólo porque falta el resumen del banco, no porque se gastó de más
    assert monthly["2026-06"]["savings"] == -300


def test_no_statements_no_coverage(conn):
    assert month_coverage(conn) == {}


def test_account_opened_later_does_not_break_earlier_months(conn):
    """Una cuenta que aparece en junio no 'debe' resúmenes de abril: si no,
    con cuentas de distinta antigüedad ningún mes sería nunca completo."""
    vieja = [_mv("2026-04-10", "x", -1), _mv("2026-06-10", "x", -1)]
    import_parsed(conn, _stmt("Vieja", "2026-04-01", "2026-06-30", vieja), "h1", "a.pdf")
    nueva = [_mv("2026-06-15", "y", -1)]
    import_parsed(conn, _stmt("Nueva", "2026-06-01", "2026-06-30", nueva), "h2", "b.pdf")
    cov = month_coverage(conn)
    assert cov["2026-04"] is True, "en abril la cuenta nueva todavía no existía"
    assert cov["2026-05"] is True
    assert cov["2026-06"] is True


def test_account_that_stops_reporting_makes_month_incomplete(conn):
    """La cuenta dejó de traer resúmenes: los meses siguientes están cojos."""
    banco = [_mv("2026-04-10", "sueldo", 100, Kind.INCOME)]
    import_parsed(conn, _stmt("Banco", "2026-04-01", "2026-04-30", banco), "h1", "a.pdf")
    tarjeta = [_mv("2026-04-15", "x", -1), _mv("2026-05-15", "x", -1)]
    import_parsed(conn, _stmt("Tarjeta", "2026-04-01", "2026-05-31", tarjeta), "h2", "b.pdf")
    cov = month_coverage(conn)
    assert cov["2026-04"] is True
    assert cov["2026-05"] is False, "falta el resumen del banco de mayo"


def test_mom_compares_last_complete_month(conn):
    """Comparar contra un mes al que le faltan extractos muestra caídas del
    100% en todo y no informa nada: se elige el último mes completo."""
    banco = [_mv("2026-05-10", "compra", -100), _mv("2026-06-10", "compra", -300)]
    import_parsed(conn, _stmt("Banco", "2026-05-01", "2026-06-30", banco), "h1", "a.pdf")
    tarjeta = [_mv("2026-05-11", "otra", -50), _mv("2026-06-11", "otra", -60), _mv("2026-07-02", "otra", -10)]
    import_parsed(conn, _stmt("Tarjeta", "2026-05-01", "2026-07-31", tarjeta), "h2", "b.pdf")

    mom = build_insights(conn)["category_mom"]
    # Julio existe pero le falta el resumen del banco: se compara junio vs mayo
    assert mom["current_month"] == "2026-06"
    assert mom["previous_month"] == "2026-05"
    assert mom["partial"] is False


def test_mom_flags_partial_when_no_complete_month(conn):
    """Si el único mes del período está incompleto, se compara igual pero
    avisando: mejor un dato con asterisco que ningún dato."""
    banco = [_mv("2026-05-10", "compra", -100), _mv("2026-06-10", "compra", -200)]
    import_parsed(conn, _stmt("Banco", "2026-05-01", "2026-06-30", banco), "h1", "a.pdf")
    tarjeta = [_mv("2026-05-11", "otra", -50)]
    import_parsed(conn, _stmt("Tarjeta", "2026-05-01", "2026-05-31", tarjeta), "h2", "b.pdf")
    # Junio no tiene el resumen de la tarjeta y es el único mes del período
    mom = build_insights(conn, "2026-06-01", "2026-06-30")["category_mom"]
    assert mom["current_month"] == "2026-06"
    assert mom["partial"] is True
