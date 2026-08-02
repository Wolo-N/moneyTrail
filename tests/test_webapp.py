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
def app_paths(tmp_path):
    rules = tmp_path / "categories.yaml"
    rules.write_text(RULES_SRC.read_text())
    return tmp_path / "data" / "moneytrail.db", rules


@pytest.fixture
def client(app_paths):
    app = create_app(*app_paths)
    app.config["TESTING"] = True
    return app.test_client()


def _seed(app_paths):
    db_path, rules = app_paths
    conn = dbmod.connect(db_path)
    import_parsed(conn, GaliciaCajaAhorroParser().parse(GALICIA_PAGES)[0], "h1", "g.pdf")
    categorize.apply_rules(conn, categorize.load_rules(rules))  # como hace /api/import
    conn.close()


# ---------------------------------------------------------------- estado


def test_state_empty(client):
    st = client.get("/api/state").get_json()
    assert st["accounts"] == []
    assert st["months"] == []
    assert st["sankey"]["links"] == []
    # Sin datos, el primer paso es explicar cómo empezar
    assert st["steps"][0]["id"] == "onboarding"


def test_state_with_data(client, app_paths):
    _seed(app_paths)
    st = client.get("/api/state").get_json()
    assert st["accounts"][0]["label"] == "Galicia Caja de Ahorro"
    assert st["months"] == ["2026-04"]
    assert "Comida/Delivery" in st["categories"]  # viene de las reglas
    assert st["health"]["transactions"] == 6
    assert st["health"]["categorized_pct"] == 100.0
    # Un solo request trae también el Sankey y los insights
    assert st["sankey"]["totals"]["income"] == 142006.67
    assert st["insights"]["totals"]["expense"] > 0


def test_state_includes_next_steps(client, app_paths):
    _seed(app_paths)
    st = client.get("/api/state").get_json()
    ids = [s["id"] for s in st["steps"]]
    # La cuenta tiene datos sólo hasta abril 2026: debe pedir los resúmenes que faltan
    assert any(i.startswith("import:") for i in ids)


def test_sankey_payload_shape(client, app_paths):
    _seed(app_paths)
    sankey = client.get("/api/state?from=2026-04&to=2026-04&usd_rate=1000").get_json()["sankey"]
    labels = [n["label"] for n in sankey["nodes"]]
    assert "Sueldo" in labels and "Galicia Caja de Ahorro" in labels
    node = next(n for n in sankey["nodes"] if n["label"] == "Sueldo")
    assert node["colorLight"].startswith("#") and node["colorDark"].startswith("#")
    assert node["drillable"] is True and node["n"] == 1
    assert all(0 <= l["source"] < len(labels) and 0 <= l["target"] < len(labels) for l in sankey["links"])


# ---------------------------------------------------------------- reglas


def test_rule_returns_new_state(client, app_paths):
    """Guardar una regla devuelve el estado nuevo: la UI no encadena requests."""
    _seed(app_paths)
    res = client.post("/api/rule", json={"match": "PLAYAS SUBTERRANEAS", "category": "Transporte/Cochera"})
    assert res.status_code == 200
    body = res.get_json()
    assert "state" in body and body["state"]["version"] > 0
    db_path, _ = app_paths
    conn = dbmod.connect(db_path)
    row = conn.execute("SELECT category FROM tx WHERE counterparty = 'PLAYAS SUBTERRANEAS'").fetchone()
    # La regla aprendida gana sobre la genérica del archivo curado
    assert row["category"] == "Transporte/Cochera"


def test_rule_written_to_learned_file_not_user_file(client, app_paths):
    _seed(app_paths)
    _, rules = app_paths
    before = rules.read_text()
    client.post("/api/rule", json={"match": "PLAYAS SUBTERRANEAS", "category": "Transporte/Cochera"})
    assert rules.read_text() == before, "el archivo curado por el usuario no debe tocarse"
    learned = categorize.read_learned(rules.parent / "learned.yaml")
    assert learned[0]["category"] == "Transporte/Cochera"
    assert learned[0]["label"] == "PLAYAS SUBTERRANEAS"


def test_rule_undo_restores_previous_category(client, app_paths):
    _seed(app_paths)
    db_path, rules = app_paths
    conn = dbmod.connect(db_path)
    original = conn.execute("SELECT category FROM tx WHERE counterparty = 'PLAYAS SUBTERRANEAS'").fetchone()[0]

    client.post("/api/rule", json={"match": "PLAYAS SUBTERRANEAS", "category": "Transporte/Cochera"})
    res = client.post("/api/rule/undo")
    assert res.status_code == 200
    assert res.get_json()["undone"]["category"] == "Transporte/Cochera"

    conn2 = dbmod.connect(db_path)
    restored = conn2.execute("SELECT category FROM tx WHERE counterparty = 'PLAYAS SUBTERRANEAS'").fetchone()[0]
    assert restored == original, "deshacer debe devolver la categoría que había antes"
    assert categorize.read_learned(rules.parent / "learned.yaml") == []


def test_undo_without_rules_fails(client, app_paths):
    _seed(app_paths)
    assert client.post("/api/rule/undo").status_code == 400


def test_rule_validation(client):
    assert client.post("/api/rule", json={"match": "", "category": "X"}).status_code == 400


def test_rule_match_is_literal_not_regex(client, app_paths):
    """Un comercio con caracteres de regex ('Payu*Ar*Uber') no debe romper."""
    _seed(app_paths)
    res = client.post("/api/rule", json={"match": "Payu*Ar*Uber", "category": "Transporte/Apps"})
    assert res.status_code == 200
    assert client.get("/api/state").status_code == 200


# ---------------------------------------------------------------- drill / búsqueda


def test_drill_category_node(client, app_paths):
    _seed(app_paths)
    data = client.get("/api/drill?node=Transporte&from=2026-04&to=2026-04").get_json()
    assert data["role"] == "expense_top"
    assert len(data["transactions"]) == 1
    assert data["transactions"][0]["counterparty"] == "PLAYAS SUBTERRANEAS"


def test_drill_account_node_has_all_movements(client, app_paths):
    _seed(app_paths)
    data = client.get("/api/drill?node=Galicia%20Caja%20de%20Ahorro").get_json()
    assert data["role"] == "account"
    assert len(data["transactions"]) == 6


def test_drill_unknown_node(client, app_paths):
    _seed(app_paths)
    assert client.get("/api/drill?node=NoExiste").status_code == 404


def test_transactions_search(client, app_paths):
    _seed(app_paths)
    all_txs = client.get("/api/transactions").get_json()["transactions"]
    assert len(all_txs) == 6
    found = client.get("/api/transactions?q=PLAYAS").get_json()["transactions"]
    assert len(found) == 1 and found[0]["counterparty"] == "PLAYAS SUBTERRANEAS"
    by_cat = client.get("/api/transactions?category=Ingresos/Sueldo").get_json()["transactions"]
    assert len(by_cat) == 1
    by_acct = client.get("/api/transactions?account=Galicia%20Caja%20de%20Ahorro").get_json()["transactions"]
    assert len(by_acct) == 6
    assert client.get("/api/transactions?account=NoExiste").get_json()["transactions"] == []


def test_export_csv(client, app_paths):
    _seed(app_paths)
    res = client.get("/api/export.csv")
    assert res.status_code == 200
    assert "attachment" in res.headers["Content-Disposition"]
    lines = res.data.decode().strip().splitlines()
    assert lines[0].startswith("fecha,cuenta,descripcion")
    assert len(lines) == 7  # encabezado + 6 movimientos


# ---------------------------------------------------------------- settings / caché


def test_settings_persist_period(client, app_paths):
    _seed(app_paths)
    client.post("/api/settings", json={"period_from": "2026-04", "period_to": "2026-04", "usd_rate": "1405"})
    st = client.get("/api/state").get_json()  # sin parámetros: usa lo guardado
    assert st["period"]["from"] == "2026-04-01"
    assert st["period"]["to"] == "2026-04-30"
    assert st["period"]["usd_rate"] == 1405.0


def test_state_version_changes_only_on_writes(client, app_paths):
    _seed(app_paths)
    v1 = client.get("/api/state").get_json()["version"]
    assert client.get("/api/state").get_json()["version"] == v1, "leer no cambia la versión"
    client.post("/api/rule", json={"match": "PLAYAS SUBTERRANEAS", "category": "Transporte/Cochera"})
    assert client.get("/api/state").get_json()["version"] > v1


def test_index_and_assets_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Soltá acá los PDFs".encode() in res.data
    js = client.get("/static/plotly.js")
    assert js.status_code == 200 and len(js.data) > 1_000_000
