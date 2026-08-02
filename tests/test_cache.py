"""El caché de lecturas: navegar no debe recalcular, escribir sí debe invalidar.

Es lo que sostiene que un click en una categoría responda en decenas de
milisegundos en vez de rearmar el Sankey y los insights en cada request.
"""

from pathlib import Path

import pytest

from fixtures.galicia_pages import PAGES as GALICIA_PAGES
from moneytrail import db as dbmod
from moneytrail.ingest import import_parsed
from moneytrail.parsers.galicia_caja_ahorro import GaliciaCajaAhorroParser
from moneytrail.webapp import server as server_mod
from moneytrail.webapp.server import create_app

RULES_SRC = Path(__file__).parent.parent / "rules" / "categories.yaml"


@pytest.fixture
def client_with_counter(tmp_path, monkeypatch):
    rules = tmp_path / "categories.yaml"
    rules.write_text(RULES_SRC.read_text())
    db_path = tmp_path / "data" / "moneytrail.db"
    conn = dbmod.connect(db_path)
    import_parsed(conn, GaliciaCajaAhorroParser().parse(GALICIA_PAGES)[0], "h1", "g.pdf")
    conn.close()

    calls = {"insights": 0}
    real = server_mod.build_insights

    def counting(*args, **kwargs):
        calls["insights"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(server_mod, "build_insights", counting)
    app = create_app(db_path, rules)
    app.config["TESTING"] = True
    return app.test_client(), calls


def test_repeated_reads_hit_the_cache(client_with_counter):
    client, calls = client_with_counter
    client.get("/api/state?from=2026-04&to=2026-04&usd_rate=1000")
    assert calls["insights"] == 1
    for _ in range(5):
        client.get("/api/state?from=2026-04&to=2026-04&usd_rate=1000")
    assert calls["insights"] == 1, "leer el mismo período no debe recalcular nada"


def test_different_period_computes_once_each(client_with_counter):
    client, calls = client_with_counter
    client.get("/api/state?from=2026-04&to=2026-04&usd_rate=1000")
    client.get("/api/state?from=2026-04&to=2026-04&usd_rate=1500")  # otro TC
    assert calls["insights"] == 2
    client.get("/api/state?from=2026-04&to=2026-04&usd_rate=1000")  # ya visto
    assert calls["insights"] == 2


def test_write_invalidates_cache(client_with_counter):
    client, calls = client_with_counter
    client.get("/api/state?from=2026-04&to=2026-04&usd_rate=1000")
    before = calls["insights"]
    client.post("/api/rule", json={"match": "PLAYAS SUBTERRANEAS", "category": "Transporte/Cochera"})
    client.get("/api/state?from=2026-04&to=2026-04&usd_rate=1000")
    assert calls["insights"] > before, "tras escribir, los datos cacheados ya no sirven"


def test_drill_reuses_the_cached_sankey(client_with_counter):
    """Abrir el detalle de un nodo no rearma el diagrama."""
    client, _ = client_with_counter
    calls = {"n": 0}
    import moneytrail.report.sankey as sankey_mod

    real = sankey_mod.build_sankey

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    sankey_mod.build_sankey = counting
    try:
        client.get("/api/state?from=2026-04&to=2026-04&usd_rate=1000")
        after_state = calls["n"]
        for _ in range(3):
            client.get("/api/drill?node=Transporte&from=2026-04&to=2026-04&usd_rate=1000")
        assert calls["n"] == after_state
    finally:
        sankey_mod.build_sankey = real
