"""Parser del Estado de Cuenta de American Express (tarjeta corporativa).

Estructura observada:
- Antes de la sección de cargos, una o más filas de pagos recibidos
  ('Gracias por su pago realizado en <banco>').
- 'Nuevos Cargos en PESOS ...' / 'Nuevos Cargos en DOLARES ...' delimitan las
  secciones de consumos en cada moneda (puede repetirse como 'Continuación'
  al cruzar de página).
- Cada movimiento son 3 líneas: '<DD> de <Mes> <descripción> <monto>', una
  línea de categoría/rubro, y 'Referencia <...>' — sólo la primera importa.
- 'Total de Cargos en PESOS/DOLARES para <titular> <monto>' da un total por
  moneda contra el que se valida la suma de los cargos.

La extracción de texto de este PDF mete un espacio errático en algunos montos
justo antes de los últimos 3 dígitos ('62 .682,00' en vez de '62.682,00'), de
forma inconsistente incluso para el mismo importe repetido — no es parte del
dato, es un artefacto de layout. _AMOUNT_TAIL_RE lo tolera.

A diferencia de Galicia, acá no se valida un saldo corrido: el resumen de
Amex, como el de Brubank tarjeta, no lo expone de forma parseable de forma
confiable; se valida contra los totales declarados por moneda.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ..models import AccountInfo, Kind, Movement, ParsedStatement, ParseError, parse_amount
from .base import register

_AMOUNT_TAIL_RE = re.compile(r"(\d+(?:\s?\.\d{3})*,\d{2})$")
_ROW_RE = re.compile(r"^(\d{1,2}) de (\w+) (.+)$")
_CARGOS_HEADER_RE = re.compile(r"^Nuevos Cargos en (PESOS|DOLARES)")
_TOTAL_CARGOS_PREFIX_RE = re.compile(r"^Total de Cargos en (PESOS|DOLARES) para ")
_BILLING_DATES_RE = re.compile(r"(\d{2})/(\d{2})/(\d{2}) (\d{2})/(\d{2})/(\d{2})")

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def _split_trailing_amount(line: str) -> tuple[str, Decimal] | None:
    m = _AMOUNT_TAIL_RE.search(line)
    if not m:
        return None
    return line[: m.start()].strip(), parse_amount(m[1])


def _infer_billing_date(pages: list[str]) -> date:
    text = "\n".join(pages)
    m = _BILLING_DATES_RE.search(text)
    if not m:
        raise ParseError("Amex: no se encontró la fecha de facturación")
    d, mo, y = m.groups()[:3]
    return date(2000 + int(y), int(mo), int(d))


class AmexTarjetaParser:
    name = "amex_tarjeta"

    def detect(self, pages: list[str]) -> bool:
        return bool(pages) and "American Express" in pages[0] and "Estado de Cuenta" in pages[0]

    def parse(self, pages: list[str]) -> list[ParsedStatement]:
        lines = [ln.strip() for page in pages for ln in page.splitlines() if ln.strip()]
        billing_date = _infer_billing_date(pages)

        movements: list[Movement] = []
        expected_totals: dict[str, Decimal] = {}
        currency = "ARS"
        in_cargos = False

        for line in lines:
            if m := _CARGOS_HEADER_RE.match(line):
                currency = "USD" if m[1] == "DOLARES" else "ARS"
                in_cargos = True
                continue
            if _TOTAL_CARGOS_PREFIX_RE.match(line):
                m2 = _TOTAL_CARGOS_PREFIX_RE.match(line)
                split = _split_trailing_amount(line)
                if split:
                    total_currency = "USD" if m2[1] == "DOLARES" else "ARS"
                    expected_totals[total_currency] = split[1]
                continue
            if m := _ROW_RE.match(line):
                split = _split_trailing_amount(m[3])
                if split is None:
                    continue  # línea que empieza como fecha pero no es un movimiento real
                description, amount = split
                mv_date = self._resolve_date(int(m[1]), m[2], billing_date)
                if in_cargos:
                    movements.append(
                        Movement(date=mv_date, description=description, amount=-amount, currency=currency, kind=Kind.EXPENSE)
                    )
                else:
                    movements.append(
                        Movement(date=mv_date, description=description, amount=amount, currency=currency, kind=Kind.CARD_PAYMENT)
                    )
            # cualquier otra línea (rubro, 'Referencia ...', membretes) se ignora

        if not movements:
            raise ParseError("Amex: no se encontraron movimientos")

        self._validate(movements, expected_totals)

        dates = [mv.date for mv in movements]
        return [
            ParsedStatement(
                account=AccountInfo(bank="American Express", product="tarjeta_credito", currency="ARS", label="American Express"),
                period_start=min(dates),
                period_end=max(dates),
                movements=movements,
            )
        ]

    @staticmethod
    def _resolve_date(day: int, month_name: str, billing_date: date) -> date:
        month = _MONTHS.get(month_name.strip().lower())
        if month is None:
            raise ParseError(f"Amex: mes no reconocido {month_name!r}")
        # Los consumos son anteriores a la facturación; si el mes del
        # movimiento es varios meses posterior al de facturación, en
        # realidad es del año calendario anterior (diciembre facturado en
        # enero, por ejemplo).
        year = billing_date.year - 1 if month > billing_date.month + 1 else billing_date.year
        return date(year, month, day)

    @staticmethod
    def _validate(movements: list[Movement], expected_totals: dict[str, Decimal]) -> None:
        for currency, expected in expected_totals.items():
            got = -sum(
                (mv.amount for mv in movements if mv.kind == Kind.EXPENSE and mv.currency == currency), Decimal(0)
            )
            if got != expected:
                raise ParseError(f"Amex: total de cargos en {currency} no cierra: {got} vs {expected}")


register(AmexTarjetaParser())
