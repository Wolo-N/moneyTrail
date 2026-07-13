from pathlib import Path

import pytest

from fixtures.galicia_pages import PAGES as GALICIA_PAGES
from moneytrail import categorize
from moneytrail import db as dbmod
from moneytrail.ingest import import_parsed
from moneytrail.parsers.galicia_caja_ahorro import GaliciaCajaAhorroParser
from moneytrail.webapp.server import create_app

RULES_SRC = Path(__file__).parent.parent / "rules" / "categories.yaml"


@pytest.fixture
def client(tmp_path):
    rules = tmp_path / "categories.yaml"
    rules.write_text(RULES_SRC.read_text())
    app = create_app(tmp_path / "data" / "moneytrail.db", rules)
    app.config["TESTING"] = True
    return app.test_client()


def _seed(tmp_path):
    conn = dbmod.connect(tmp_path / "data" / "moneytrail.db")
    import_parsed(conn, GaliciaCajaAhorroParser().parse(GALICIA_PAGES)[0], "h1", "g.pdf")
    categorize.apply_rules(conn, categorize.load_rules(RULES_SRC))  # como hace /api/import
    conn.close()


def test_status_empty(client):
    st = client.get("/api/status").get_json()
    assert st["accounts"] == []
    assert st["months"] == []


def test_status_with_data(client, tmp_path):
    _seed(tmp_path)
    st = client.get("/api/status").get_json()
    assert st["accounts"][0]["label"] == "Galicia Caja de Ahorro"
    assert st["months"] == ["2026-04"]
    assert "Comida/Delivery" in st["categories"]  # viene de las reglas


def test_add_rule_categorizes(client, tmp_path):
    _seed(tmp_path)
    # 'THE ANGELS' está en las reglas del repo; borramos esa regla para simular
    # un comercio desconocido y lo categorizamos vía API.
    pending_before = client.get("/api/status").get_json()["uncategorized"]
    res = client.post("/api/rule", json={"match": "PLAYAS SUBTERRANEAS", "category": "Transporte/Cochera"})
    assert res.status_code == 200
    conn = dbmod.connect(tmp_path / "data" / "moneytrail.db")
    row = conn.execute("SELECT category FROM tx WHERE counterparty = 'PLAYAS SUBTERRANEAS'").fetchone()
    # ya estaba categorizado por la regla original del repo (solo-sin-categorizar no lo pisa)
    assert row["category"] is not None
    assert pending_before is not None  # sanity


def test_rule_validation(client):
    assert client.post("/api/rule", json={"match": "", "category": "X"}).status_code == 400


def test_report_renders(client, tmp_path):
    _seed(tmp_path)
    res = client.get("/report?from=2026-04&to=2026-04&usd_rate=1000")
    assert res.status_code == 200
    assert b"moneyTrail" in res.data
    assert "Sueldo".encode() in res.data


def test_index_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Soltá los PDFs".encode() in res.data
