"""Un mismo PDF puede traer varias cuentas (el resumen de cuenta Brubank trae
caja de ahorro ARS + USD): cada una necesita su propia clave de dedupe, y
re-importar el mismo archivo no debe duplicar ninguna de las dos."""

from pathlib import Path

import pytest

from fixtures.brubank_cuenta_pages import PAGES
from moneytrail import ingest


@pytest.fixture
def fake_pdf(tmp_path, monkeypatch):
    pdf_path = tmp_path / "brubank_cuenta.pdf"
    pdf_path.write_bytes(b"contenido no importa: extract_pages esta mockeado")
    monkeypatch.setattr(ingest, "extract_pages", lambda p: PAGES)
    return pdf_path


def test_multi_account_file_imports_both_accounts(conn, fake_pdf):
    result = ingest.import_file(conn, fake_pdf)
    assert result.status == "imported"
    assert result.parser == "brubank_cuenta"
    assert result.new_txs == 3 + 2  # ARS + USD

    labels = {r["label"] for r in conn.execute("SELECT DISTINCT label FROM account")}
    assert labels == {"Brubank Caja de ahorro (ARS)", "Brubank Caja de ahorro (USD)"}


def test_reimport_same_file_is_noop(conn, fake_pdf):
    ingest.import_file(conn, fake_pdf)
    result = ingest.import_file(conn, fake_pdf)
    assert result.status == "skipped_duplicate"
    total_txs = conn.execute("SELECT COUNT(*) FROM tx").fetchone()[0]
    assert total_txs == 5  # no se duplicó nada


def test_partial_reimport_only_adds_new_account(conn, fake_pdf, monkeypatch):
    # Importamos primero solo el bloque ARS (como si el PDF original sólo
    # trajera esa cuenta); al re-importar el PDF completo, la cuenta USD
    # debe sumarse como nueva sin tocar la ARS ya importada.
    from moneytrail.parsers.brubank_cuenta import BrubankCuentaParser

    ars_only = [s for s in BrubankCuentaParser().parse(PAGES) if s.account.currency == "ARS"]
    monkeypatch.setattr(ingest, "extract_pages", lambda p: PAGES)
    monkeypatch.setattr(
        "moneytrail.parsers.brubank_cuenta.BrubankCuentaParser.parse",
        lambda self, pages: ars_only,
    )
    first = ingest.import_file(conn, fake_pdf)
    assert first.new_txs == 3

    monkeypatch.undo()
    monkeypatch.setattr(ingest, "extract_pages", lambda p: PAGES)
    second = ingest.import_file(conn, fake_pdf)
    assert second.status == "imported"
    assert second.new_txs == 2  # sólo la cuenta USD, nueva

    labels = {r["label"] for r in conn.execute("SELECT DISTINCT label FROM account")}
    assert labels == {"Brubank Caja de ahorro (ARS)", "Brubank Caja de ahorro (USD)"}
