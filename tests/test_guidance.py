"""El panel que hace repetible el ritual mensual: qué falta y qué hacer."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from moneytrail import categorize
from moneytrail.guidance import health, month_label, next_steps
from moneytrail.ingest import import_parsed
from moneytrail.models import AccountInfo, Kind, Movement, ParsedStatement

RULES = Path(__file__).parent.parent / "rules" / "categories.yaml"


def _stmt(label, start, end, movements):
    return ParsedStatement(
        account=AccountInfo(bank="Test", product="caja_ahorro", currency="ARS", label=label),
        period_start=date.fromisoformat(start),
        period_end=date.fromisoformat(end),
        movements=movements,
    )


def _mv(day, desc, amount, kind=Kind.EXPENSE):
    return Movement(date=date.fromisoformat(day), description=desc, amount=Decimal(str(amount)), kind=kind)


def test_month_label():
    assert month_label("2026-06") == "junio 2026"
    assert month_label("2026-01") == "enero 2026"


def test_empty_db_explains_how_to_start(conn):
    steps = next_steps(conn, today=date(2026, 7, 14))
    assert len(steps) == 1
    assert steps[0]["id"] == "onboarding"
    assert steps[0]["action"] == "import"


def test_flags_missing_statement(conn):
    """Estamos en julio; el resumen de junio debería estar y no está."""
    import_parsed(conn, _stmt("Galicia", "2026-04-01", "2026-04-30", [_mv("2026-04-10", "X", -100)]), "h", "g.pdf")
    steps = next_steps(conn, today=date(2026, 7, 14))
    imports = [s for s in steps if s["id"] == "import:missing"]
    assert len(imports) == 1
    assert "1 resumen de junio 2026" in imports[0]["title"]
    assert "Galicia (último: abril 2026)" in imports[0]["detail"]
    assert imports[0]["accounts"] == ["Galicia"]


def test_missing_statements_grouped_in_one_step(conn):
    """Varias cuentas atrasadas se agrupan: cuatro tarjetas iguales no se leen."""
    for label in ("Galicia", "Brubank ARS", "Brubank USD"):
        import_parsed(
            conn, _stmt(label, "2026-05-01", "2026-05-31", [_mv("2026-05-10", "X", -100)]), f"h{label}", "g.pdf"
        )
    steps = next_steps(conn, today=date(2026, 7, 14))
    imports = [s for s in steps if s["id"] == "import:missing"]
    assert len(imports) == 1
    assert "Faltan 3 resúmenes de junio 2026" in imports[0]["title"]
    assert set(imports[0]["accounts"]) == {"Galicia", "Brubank ARS", "Brubank USD"}


def test_account_up_to_date_is_not_flagged(conn):
    import_parsed(conn, _stmt("Galicia", "2026-06-01", "2026-06-30", [_mv("2026-06-10", "X", -100)]), "h", "g.pdf")
    steps = next_steps(conn, today=date(2026, 7, 14))
    assert not [s for s in steps if s["id"].startswith("import:")]


def test_current_month_is_not_demanded_yet(conn):
    """El resumen de julio todavía no existe el 14 de julio: no hay que pedirlo."""
    import_parsed(conn, _stmt("Galicia", "2026-06-01", "2026-06-30", [_mv("2026-06-10", "X", -100)]), "h", "g.pdf")
    steps = next_steps(conn, today=date(2026, 7, 14))
    assert [s["id"] for s in steps] != ["import:Galicia"]


def test_flags_uncategorized_with_amount(conn):
    import_parsed(
        conn,
        _stmt("Galicia", "2026-06-01", "2026-06-30", [_mv("2026-06-10", "COMERCIO RARO", -5000)]),
        "h",
        "g.pdf",
    )
    steps = next_steps(conn, today=date(2026, 7, 14))
    step = next(s for s in steps if s["id"] == "categorize")
    assert "1 gastos sin categorizar" in step["title"]
    assert "5.000" in step["detail"]
    assert step["action"] == "categorize"


def test_flags_unreconciled_internal_flows(conn):
    import_parsed(
        conn,
        _stmt("Galicia", "2026-06-01", "2026-06-30", [_mv("2026-06-10", "PAGO TARJETA", -1000, Kind.CARD_PAYMENT)]),
        "h",
        "g.pdf",
    )
    steps = next_steps(conn, today=date(2026, 7, 14))
    assert any(s["id"] == "reconcile" for s in steps)


def test_all_clear(conn):
    movements = [_mv("2026-06-10", "RAPPI", -100)]
    import_parsed(conn, _stmt("Galicia", "2026-06-01", "2026-06-30", movements), "h", "g.pdf")
    categorize.apply_rules(conn, categorize.load_rules(RULES))
    steps = next_steps(conn, today=date(2026, 7, 14))
    assert [s["id"] for s in steps] == ["ok"]
    assert steps[0]["severity"] == "ok"


def test_health_metrics(conn):
    movements = [_mv("2026-06-10", "RAPPI", -100), _mv("2026-06-11", "DESCONOCIDO", -50)]
    import_parsed(conn, _stmt("Galicia", "2026-06-01", "2026-06-30", movements), "h", "g.pdf")
    categorize.apply_rules(conn, categorize.load_rules(RULES))
    h = health(conn)
    assert h["transactions"] == 2
    assert h["statements"] == 1
    assert h["accounts"] == 1
    assert h["categorized_pct"] == 50.0
