"""Parser del resumen de Tarjeta de Crédito VISA de Banco Galicia.

Estructura observada:

    CONSOLIDADO            PESOS      DÓLARES
    SALDO ANTERIOR      224.169,75       0,00
    07-07-26 SU PAGO EN PESOS        -224.169,75
    DETALLE DEL CONSUMO
    FECHA  REFERENCIA  CUOTA  COMPROBANTE  PESOS  DÓLARES
    03-07-26 K JUMBO PACHECO      196227   16.797,86
    ...
    TARJETA 9796 Total Consumos de ...   246.044,86   0,00
    30-07-26 IMPUESTO DE SELLOS $          8.881,60
    TOTAL A PAGAR                        749.015,16   0,00

A diferencia de los otros resúmenes, acá **la posición horizontal importa**:
pesos y dólares son dos columnas distintas y un importe pertenece a una o a
otra según dónde cae, no según cómo está escrito. Por eso se trabaja sobre las
palabras con coordenadas en vez del texto plano.

Los subtotales por tarjeta van *después* de sus consumos (al revés que en
Brubank), así que las filas se acumulan y se cierran al llegar a la línea
'TARJETA NNNN Total Consumos'.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ..models import AccountInfo, Kind, Movement, ParsedStatement, ParseError, parse_amount
from .base import register

# Fronteras de columna, tomadas del layout real (ver docstring). Se usan rangos
# holgados: alcanza con separar una columna de la otra, no con clavar el pixel.
_MARKER_X = (66, 84)          # 'K' / '*': tipo de operación
_DESC_X = (84, 362)           # REFERENCIA (comercio) y CUOTA
_VOUCHER_X = (362, 440)       # COMPROBANTE
_AMOUNT_MIN_X1 = 470          # todo importe termina a la derecha de acá
_ARS_USD_SPLIT_X1 = 520       # a la izquierda pesos, a la derecha dólares

_ROW_DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{2}$")
_CYCLE_DATE_RE = re.compile(r"^(\d{2})-([A-Za-z]{3})-(\d{2})$")
_VOUCHER_RE = re.compile(r"^\d+$")

_MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _rows_from_words(words: list[dict], tolerance: float = 2.5) -> list[list[dict]]:
    """Agrupa palabras en filas visuales. Se usa tolerancia en vez de comparar
    el `top` exacto porque dentro de una misma fila los importes suelen quedar
    un pelo desalineados y si no se separarían en dos."""
    rows: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(word["top"] - rows[-1][0]["top"]) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    return [sorted(row, key=lambda w: w["x0"]) for row in rows]


def _amounts(row: list[dict]) -> list[tuple[Decimal, str]]:
    """Importes de la fila con su moneda, deducida de la columna en que caen."""
    found = []
    for word in row:
        if word["x1"] < _AMOUNT_MIN_X1:
            continue
        try:
            value = parse_amount(word["text"])
        except (InvalidOperation, ValueError):
            continue
        found.append((value, "ARS" if word["x1"] <= _ARS_USD_SPLIT_X1 else "USD"))
    return found


def _text_between(row: list[dict], x_range: tuple[float, float]) -> str:
    lo, hi = x_range
    return " ".join(w["text"] for w in row if lo <= w["x0"] < hi).strip()


class GaliciaVisaParser:
    name = "galicia_visa"

    def detect(self, pages: list[str]) -> bool:
        return bool(pages) and "Tarjeta Crédito VISA" in pages[0] and "DETALLE DEL CONSUMO" in "\n".join(pages)

    def parse(self, pages: list[str]) -> list[ParsedStatement]:
        raise ParseError("Este parser necesita las coordenadas del PDF (usar parse_words)")

    def parse_words(self, pages: list[str], words_by_page: list[list[dict]]) -> list[ParsedStatement]:
        movements: list[Movement] = []
        opening: Decimal | None = None
        total: Decimal | None = None
        card_subtotals: list[tuple[str, Decimal]] = []
        pending: list[Movement] = []  # consumos aún no atribuidos a una tarjeta
        card_totals: dict[str, Decimal] = {}

        for words in words_by_page:
            for row in _rows_from_words(words):
                text = " ".join(w["text"] for w in row)
                amounts = _amounts(row)

                if text.startswith("SALDO ANTERIOR") and amounts:
                    opening = amounts[0][0]
                    continue
                if text.startswith("TOTAL A PAGAR") and amounts:
                    total = amounts[0][0]
                    continue
                if text.startswith("TARJETA ") and "Total Consumos" in text and amounts:
                    card = row[1]["text"]
                    card_subtotals.append((card, amounts[0][0]))
                    for mv in pending:
                        mv.detail = f"Tarjeta {card}"
                    card_totals[card] = -sum(
                        (mv.amount for mv in pending if mv.currency == "ARS" and mv.kind == Kind.EXPENSE),
                        Decimal(0),
                    )
                    movements.extend(pending)
                    pending = []
                    continue

                if not row or not _ROW_DATE_RE.match(row[0]["text"]) or not amounts:
                    continue

                mv_date = datetime.strptime(row[0]["text"], "%d-%m-%y").date()
                # El '$' que precede al importe cae dentro de la columna de
                # descripción; no es parte del nombre del movimiento.
                description = _text_between(row, _DESC_X).rstrip(" $").strip()
                voucher = next(
                    (w["text"] for w in row if _VOUCHER_X[0] <= w["x0"] < _VOUCHER_X[1] and _VOUCHER_RE.match(w["text"])),
                    "",
                )
                marker = _text_between(row, _MARKER_X)
                value, currency = amounts[0]
                upper = description.upper()

                if "SU PAGO" in upper:
                    # Viene con signo negativo (reduce el saldo de la tarjeta);
                    # para nosotros un pago recibido es un crédito.
                    movements.append(
                        Movement(date=mv_date, description=description, amount=abs(value),
                                 currency=currency, kind=Kind.CARD_PAYMENT)
                    )
                elif "IMPUESTO" in upper or "IVA" in upper:
                    movements.append(
                        Movement(date=mv_date, description=description, amount=-value,
                                 currency=currency, kind=Kind.TAX)
                    )
                else:
                    # El número de tarjeta se conoce recién al llegar al
                    # subtotal, unas filas más abajo: se completa ahí.
                    pending.append(
                        Movement(date=mv_date, description=description, amount=-value, currency=currency,
                                 ref=voucher, counterparty="" if marker in ("K", "*") else marker,
                                 kind=Kind.EXPENSE)
                    )

        movements.extend(pending)
        if not movements:
            raise ParseError("Galicia VISA: no se encontraron movimientos")

        self._validate(movements, card_subtotals, card_totals, opening, total)
        period_start, period_end = self._period(pages, movements)
        return [
            ParsedStatement(
                account=AccountInfo(bank="Banco Galicia", product="tarjeta_credito", currency="ARS",
                                    label="Galicia Tarjeta VISA"),
                period_start=period_start,
                period_end=period_end,
                opening_balance=opening,
                closing_balance=total,
                movements=movements,
            )
        ]

    @staticmethod
    def _period(pages: list[str], movements: list[Movement]) -> tuple[date, date]:
        """Del ciclo de facturación del encabezado: cierre anterior y actual.
        Si no se puede leer, se cae a las fechas de los movimientos."""
        cycle: list[date] = []
        for token in pages[0].split():
            if m := _CYCLE_DATE_RE.match(token):
                month = _MESES.get(m[2].lower())
                if month:
                    cycle.append(date(2000 + int(m[3]), month, int(m[1])))
        if len(cycle) >= 3:
            return cycle[0], cycle[2]
        dates = [mv.date for mv in movements]
        return min(dates), max(dates)

    @staticmethod
    def _validate(
        movements: list[Movement],
        card_subtotals: list[tuple[str, Decimal]],
        card_totals: dict[str, Decimal],
        opening: Decimal | None,
        total: Decimal | None,
    ) -> None:
        for card, declared in card_subtotals:
            got = card_totals.get(card, Decimal(0))
            if got != declared:
                raise ParseError(
                    f"Galicia VISA: los consumos de la tarjeta {card} no cierran: {got} vs {declared}"
                )
        if opening is not None and total is not None:
            # El resumen arma: total = saldo anterior + consumos + impuestos − pagos.
            # Con nuestros signos (consumo negativo, pago positivo) eso es
            # simplemente saldo anterior − Σ(movimientos).
            calculated = opening - sum((mv.amount for mv in movements if mv.currency == "ARS"), Decimal(0))
            if calculated != total:
                raise ParseError(f"Galicia VISA: el total a pagar no cierra: {calculated} vs {total}")


register(GaliciaVisaParser())
