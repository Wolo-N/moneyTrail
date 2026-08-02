"""Ingesta: PDF → parser → normalización → SQLite, de forma idempotente."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import db
from .models import ParsedStatement
from .parsers import find_parser


@dataclass
class ImportResult:
    source: str
    status: str  # 'imported' | 'skipped_duplicate' | 'no_parser' | 'error'
    parser: str = ""
    new_txs: int = 0
    dup_txs: int = 0
    error: str = ""


def extract_pages(pdf_path: Path) -> list[str]:
    import pdfplumber  # import diferido: es la dependencia más pesada

    with pdfplumber.open(pdf_path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def extract_words(pdf_path: Path) -> list[list[dict]]:
    """Palabras con coordenadas, por página.

    Sólo la piden los parsers cuyo formato tiene columnas que el texto plano no
    distingue (el resumen VISA de Galicia separa pesos y dólares por posición,
    no por notación: sin las coordenadas, un consumo en dólares se leería como
    pesos).
    """
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        return [page.extract_words() for page in pdf.pages]


def import_parsed(
    conn: sqlite3.Connection, stmt: ParsedStatement, file_hash: str, source: str
) -> tuple[int, int]:
    """Guarda un extracto ya parseado. Devuelve (movimientos nuevos, duplicados)."""
    account_id = db.get_or_create_account(conn, stmt.account)
    statement_id = db.insert_statement(conn, account_id, stmt, file_hash, source)
    new = dup = 0
    for mv in stmt.movements:
        if db.insert_movement(conn, statement_id, account_id, stmt.account.label, mv):
            new += 1
        else:
            dup += 1
    conn.commit()
    db.bump_version(conn)
    return new, dup


def import_file(conn: sqlite3.Connection, pdf_path: Path) -> ImportResult:
    source = pdf_path.name
    file_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    try:
        pages = extract_pages(pdf_path)
        parser = find_parser(pages)
        if parser is None:
            return ImportResult(source, "no_parser")
        if hasattr(parser, "parse_words"):
            stmts = parser.parse_words(pages, extract_words(pdf_path))
        else:
            stmts = parser.parse(pages)

        # Un PDF casi siempre trae una sola cuenta (el hash del archivo ya la
        # identifica), pero el resumen de cuenta de Brubank trae varias
        # subcuentas en un mismo archivo: cada una necesita su propia clave de
        # dedupe derivada, o la segunda pisaría el UNIQUE de la primera.
        multi = len(stmts) > 1
        total_new = total_dup = 0
        any_new = False
        for i, stmt in enumerate(stmts):
            stmt_hash = f"{file_hash}:{i}" if multi else file_hash
            if db.statement_exists(conn, stmt_hash):
                continue
            any_new = True
            new, dup = import_parsed(conn, stmt, stmt_hash, source)
            total_new += new
            total_dup += dup
        if not any_new:
            return ImportResult(source, "skipped_duplicate")
        return ImportResult(source, "imported", parser.name, total_new, total_dup)
    except Exception as exc:  # noqa: BLE001 — un PDF roto no debe frenar el lote
        conn.rollback()
        return ImportResult(source, "error", error=str(exc))


def import_path(conn: sqlite3.Connection, path: Path, archive_dir: Path | None = None) -> list[ImportResult]:
    pdfs = sorted(path.glob("*.pdf")) if path.is_dir() else [path]
    results = []
    for pdf in pdfs:
        result = import_file(conn, pdf)
        results.append(result)
        if archive_dir is not None and result.status == "imported":
            archive_dir.mkdir(parents=True, exist_ok=True)
            pdf.rename(archive_dir / pdf.name)
    return results
