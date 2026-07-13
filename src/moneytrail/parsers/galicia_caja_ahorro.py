"""Parser del resumen de Caja de Ahorro en Pesos de Banco Galicia.

Estructura observada:
- Encabezado con saldos inicial/final (dos montos '$...' sueltos) y período
  en una línea 'CBU dd/mm/yyyy dd/mm/yyyy'.
- Movimientos: la primera línea es 'dd/mm/aa DESCRIPCION [-]crédito/débito saldo';
  le siguen líneas de continuación (contraparte, CUIT, banco) hasta el próximo
  movimiento. Los débitos vienen con signo '-'.
- Cierra con 'Total $ <créditos> -$ <débitos> $ <saldo final>'.

Validaciones: saldo corrido fila a fila y totales del pie contra la suma.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from ..models import AccountInfo, Movement, ParsedStatement, ParseError, parse_amount
from .base import register

_MOVEMENT_RE = re.compile(r"^(\d{2}/\d{2}/\d{2}) (.+?) (-?[\d.]+,\d{2}) (-?[\d.]+,\d{2})$")
_PERIOD_RE = re.compile(r"(\d{2}/\d{2}/\d{4}) (\d{2}/\d{2}/\d{4})")
_BALANCE_RE = re.compile(r"^\$([\d.]+,\d{2})$")
_TOTAL_RE = re.compile(r"^Total \$ ([\d.]+,\d{2}) -\$ ([\d.]+,\d{2}) \$ (-?[\d.]+,\d{2})$")
_JUNK_RES = [
    re.compile(r"^Resumen de Caja de Ahorro en Pesos( Página \d+ / \d+)?$"),
    re.compile(r"^\d+P$"),  # código de barras del pie, p. ej. 20260506049040385P
    re.compile(r"^Fecha Descripción Origen Crédito Débito Saldo$"),
]
# Líneas de detalle que no sirven como contraparte: CUITs, CBUs, 'CU <cuil>', números de tarjeta
_NUMERIC_LINE_RE = re.compile(r"^(CU )?[\d\s.-]+$")


def _parse_date(d: str) -> date:
    return datetime.strptime(d, "%d/%m/%y").date()


class GaliciaCajaAhorroParser:
    name = "galicia_caja_ahorro"

    def detect(self, pages: list[str]) -> bool:
        return bool(pages) and "Resumen de Caja de Ahorro en Pesos" in pages[0]

    def parse(self, pages: list[str]) -> list[ParsedStatement]:
        lines = [ln.strip() for page in pages for ln in page.splitlines() if ln.strip()]

        period_start, period_end = self._parse_period(lines)
        opening, closing = self._parse_balances(lines)

        movements: list[Movement] = []
        totals: tuple[Decimal, Decimal, Decimal] | None = None
        current: Movement | None = None
        details: list[str] = []
        in_movements = False

        def flush() -> None:
            nonlocal current, details
            if current is not None:
                current.detail = "\n".join(details)
                current.counterparty = self._counterparty(details)
                movements.append(current)
            current, details = None, []

        for line in lines:
            if not in_movements:
                if line == "Movimientos":
                    in_movements = True
                continue
            if any(rx.match(line) for rx in _JUNK_RES):
                continue
            if m := _TOTAL_RE.match(line):
                flush()
                totals = (parse_amount(m[1]), parse_amount(m[2]), parse_amount(m[3]))
                break
            if m := _MOVEMENT_RE.match(line):
                flush()
                current = Movement(
                    date=_parse_date(m[1]),
                    description=m[2],
                    amount=parse_amount(m[3]),
                    currency="ARS",
                )
                details.append(f"__saldo__{m[4]}")  # se valida y descarta después
            elif current is not None:
                details.append(line)
        flush()

        movements = self._validate(movements, opening, closing, totals)

        return [
            ParsedStatement(
                account=AccountInfo(
                    bank="Banco Galicia", product="caja_ahorro", currency="ARS", label="Galicia Caja de Ahorro"
                ),
                period_start=period_start,
                period_end=period_end,
                opening_balance=opening,
                closing_balance=closing,
                movements=movements,
            )
        ]

    @staticmethod
    def _parse_period(lines: list[str]) -> tuple[date, date]:
        for line in lines:
            if m := _PERIOD_RE.search(line):
                fmt = "%d/%m/%Y"
                return datetime.strptime(m[1], fmt).date(), datetime.strptime(m[2], fmt).date()
        raise ParseError("Galicia: no se encontró el período de movimientos")

    @staticmethod
    def _parse_balances(lines: list[str]) -> tuple[Decimal, Decimal]:
        balances = []
        for line in lines:
            if line == "Movimientos":
                break
            if m := _BALANCE_RE.match(line):
                balances.append(parse_amount(m[1]))
        if len(balances) != 2:
            raise ParseError(f"Galicia: se esperaban 2 saldos en el encabezado, hay {len(balances)}")
        return balances[0], balances[1]

    @staticmethod
    def _counterparty(details: list[str]) -> str:
        for line in details:
            if not line.startswith("__saldo__") and not _NUMERIC_LINE_RE.match(line):
                return line
        return ""

    @staticmethod
    def _validate(
        movements: list[Movement],
        opening: Decimal,
        closing: Decimal,
        totals: tuple[Decimal, Decimal, Decimal] | None,
    ) -> list[Movement]:
        # Saldo corrido: cada fila trae el saldo resultante; detecta filas perdidas o mal parseadas.
        running = opening
        for mv in movements:
            running += mv.amount
            stated_raw = next((d for d in mv.detail.splitlines() if d.startswith("__saldo__")), None)
            if stated_raw is not None:
                stated = parse_amount(stated_raw.removeprefix("__saldo__"))
                if stated != running:
                    raise ParseError(
                        f"Galicia: saldo corrido no cierra en {mv.date} {mv.description!r}: "
                        f"calculado {running}, extracto {stated}"
                    )
            mv.detail = "\n".join(d for d in mv.detail.splitlines() if not d.startswith("__saldo__"))
        if running != closing:
            raise ParseError(f"Galicia: saldo final calculado {running} != extracto {closing}")
        if totals is not None:
            credits = sum((mv.amount for mv in movements if mv.amount > 0), Decimal(0))
            debits = sum((-mv.amount for mv in movements if mv.amount < 0), Decimal(0))
            if (credits, debits) != (totals[0], totals[1]):
                raise ParseError(
                    f"Galicia: totales no cierran: créditos {credits} vs {totals[0]}, "
                    f"débitos {debits} vs {totals[1]}"
                )
        return movements


register(GaliciaCajaAhorroParser())
