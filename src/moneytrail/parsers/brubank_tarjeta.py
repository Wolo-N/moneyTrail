"""Parser del resumen de tarjeta de crédito de Brubank (ARS + USD).

Estructura observada:
- Secciones por tarjeta: 'Tarjeta NNNN <titular> Subtotal: U$S x $ y' seguida de
  consumos 'yyyy-mm-dd #ref descripción (U$S monto | $ monto)'.
- Secciones 'Comisiones' e 'Intereses' con el mismo formato de línea.
- 'Impuestos': líneas 'Descripción $ monto' sin fecha, hasta su 'Total'.
- 'Pagos' / 'Pago en dólares': líneas 'yyyy-mm-dd $ monto' (créditos a la tarjeta).

Los consumos, comisiones e impuestos se normalizan con monto negativo; los pagos,
positivo. Valida los subtotales por tarjeta y los totales de impuestos y pagos.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from ..models import AccountInfo, Kind, Movement, ParsedStatement, ParseError, parse_amount
from .base import register

_CARD_RE = re.compile(r"^Tarjeta (\d{4}) (.+?) Subtotal: U\$S ([\d.,]+) \$ ([\d.,]+)$")
_CONSUMPTION_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d+) (.+?) (U\$S|\$) ([\d.,]+)$")
_TAX_RE = re.compile(r"^(.+?) \$ ([\d.,]+)$")
_PAYMENT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (U\$S|\$) ([\d.,]+)$")
_TOTAL_RE = re.compile(r"^Total (?:U\$S |\$ )?([\d.,]+)$")


class BrubankTarjetaParser:
    name = "brubank_tarjeta"

    def detect(self, pages: list[str]) -> bool:
        text = "\n".join(pages)
        return "Ciclo de facturación" in text and "Brubank" in text

    def parse(self, pages: list[str]) -> list[ParsedStatement]:
        lines = [ln.strip() for page in pages for ln in page.splitlines() if ln.strip()]

        movements: list[Movement] = []
        section = ""  # '', 'card', 'comisiones', 'intereses', 'impuestos', 'pagos', 'pagos_usd'
        card = ""
        card_expected: dict[str, tuple[Decimal, Decimal]] = {}
        tax_total: Decimal | None = None
        payments_expected: dict[str, Decimal] = {}

        for line in lines:
            if m := _CARD_RE.match(line):
                card = m[1]
                section = "card"
                card_expected[card] = (parse_amount(m[3]), parse_amount(m[4]))
                continue
            if line == "Comisiones":
                section = "comisiones"
                continue
            if line == "Intereses":
                section = "intereses"
                continue
            if line == "Impuestos":
                section = "impuestos"
                continue
            if line == "Pagos":
                section = "pagos"
                continue
            if line == "Pago en dólares":
                section = "pagos_usd"
                continue
            if line in ("Cuotas a vencer", "Tasas", "Legales"):
                section = ""
                continue

            if section == "card" and (m := _CONSUMPTION_RE.match(line)):
                movements.append(
                    Movement(
                        date=date.fromisoformat(m[1]),
                        description=m[3],
                        detail=f"Tarjeta {card}",
                        amount=-parse_amount(m[5]),
                        currency="USD" if m[4] == "U$S" else "ARS",
                        ref=m[2],
                        kind=Kind.EXPENSE,
                    )
                )
            elif section in ("comisiones", "intereses") and (m := _CONSUMPTION_RE.match(line)):
                movements.append(
                    Movement(
                        date=date.fromisoformat(m[1]),
                        description=m[3],
                        amount=-parse_amount(m[5]),
                        currency="USD" if m[4] == "U$S" else "ARS",
                        ref=m[2],
                        kind=Kind.FEE if section == "comisiones" else Kind.INTEREST,
                    )
                )
            elif section == "impuestos":
                if m := _TOTAL_RE.match(line):
                    tax_total = parse_amount(m[1])
                    section = ""
                elif (m := _TAX_RE.match(line)) and not line.startswith("Descripción"):
                    movements.append(
                        Movement(
                            date=max((mv.date for mv in movements), default=date.today()),
                            description=m[1],
                            amount=-parse_amount(m[2]),
                            currency="ARS",
                            kind=Kind.TAX,
                        )
                    )
            elif section in ("pagos", "pagos_usd"):
                if m := _TOTAL_RE.match(line):
                    payments_expected[section] = parse_amount(m[1])
                    section = ""
                elif m := _PAYMENT_RE.match(line):
                    movements.append(
                        Movement(
                            date=date.fromisoformat(m[1]),
                            description="Pago recibido",
                            amount=parse_amount(m[3]),
                            currency="USD" if m[2] == "U$S" else "ARS",
                            kind=Kind.CARD_PAYMENT,
                        )
                    )

        if not movements:
            raise ParseError("Brubank: no se encontraron movimientos")

        self._validate(movements, card_expected, tax_total, payments_expected)

        dates = [mv.date for mv in movements]
        return [
            ParsedStatement(
                account=AccountInfo(
                    bank="Brubank", product="tarjeta_credito", currency="ARS", label="Brubank Tarjeta de Crédito"
                ),
                period_start=min(dates),
                period_end=max(dates),
                movements=movements,
            )
        ]

    @staticmethod
    def _validate(
        movements: list[Movement],
        card_expected: dict[str, tuple[Decimal, Decimal]],
        tax_total: Decimal | None,
        payments_expected: dict[str, Decimal],
    ) -> None:
        for card, (usd, ars) in card_expected.items():
            got_usd = -sum(
                (mv.amount for mv in movements if mv.detail == f"Tarjeta {card}" and mv.currency == "USD"),
                Decimal(0),
            )
            got_ars = -sum(
                (mv.amount for mv in movements if mv.detail == f"Tarjeta {card}" and mv.currency == "ARS"),
                Decimal(0),
            )
            if (got_usd, got_ars) != (usd, ars):
                raise ParseError(
                    f"Brubank: subtotal tarjeta {card} no cierra: "
                    f"USD {got_usd} vs {usd}, ARS {got_ars} vs {ars}"
                )
        if tax_total is not None:
            got = -sum((mv.amount for mv in movements if mv.kind == Kind.TAX), Decimal(0))
            if got != tax_total:
                raise ParseError(f"Brubank: total de impuestos no cierra: {got} vs {tax_total}")
        checks = {"pagos": "ARS", "pagos_usd": "USD"}
        for section, currency in checks.items():
            if section in payments_expected:
                got = sum(
                    (mv.amount for mv in movements if mv.kind == Kind.CARD_PAYMENT and mv.currency == currency),
                    Decimal(0),
                )
                if got != payments_expected[section]:
                    raise ParseError(
                        f"Brubank: total de pagos {currency} no cierra: {got} vs {payments_expected[section]}"
                    )


register(BrubankTarjetaParser())
