"""Contrato de los parsers: reciben el texto por página, devuelven una lista de
ParsedStatement (casi siempre una sola; un PDF de Brubank puede traer varias
subcuentas — caja de ahorro en ARS, cuenta remunerada, caja de ahorro en USD —
y cada una se modela como una cuenta propia).

Trabajan sobre texto (no sobre el PDF) para que los tests puedan usar fixtures
de texto sintéticas sin PDFs reales.
"""

from __future__ import annotations

from typing import Protocol

from ..models import ParsedStatement


class StatementParser(Protocol):
    name: str

    def detect(self, pages: list[str]) -> bool:
        """¿Este parser entiende este documento?"""
        ...

    def parse(self, pages: list[str]) -> list[ParsedStatement]:
        ...


_REGISTRY: list[StatementParser] = []


def register(parser: StatementParser) -> StatementParser:
    _REGISTRY.append(parser)
    return parser


def find_parser(pages: list[str]) -> StatementParser | None:
    for parser in _REGISTRY:
        if parser.detect(pages):
            return parser
    return None
