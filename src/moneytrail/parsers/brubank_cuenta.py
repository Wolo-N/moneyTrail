"""Parser del resumen de cuenta de Brubank ('Mi cuenta').

Un mismo PDF trae varias subcuentas en secuencia (caja de ahorro en ARS,
cuenta remunerada, caja de ahorro en USD...), cada una como un bloque:

    Mi cuenta Resumen
    Tipo <tipo> Saldo Inicial <monto>
    Moneda <moneda> Créditos <monto>
    CUIT <cuit> Débitos <monto>
    [Número <numero>]
    [CBU <cbu>]
    Imp. Trans. Financieras <monto> Saldo Final <monto>
    Movimientos                              (o 'Sin Movimientos')
    Fecha #Ref Descripción Débito Crédito Saldo
    <fila> ...

Cada bloque se modela como una cuenta propia (mismo banco, distinto tipo o
moneda). Las subcuentas sin movimientos ('Sin Movimientos') se descartan: no
aportan nada y evitan ensuciar la lista de cuentas con saldos siempre en cero.

Las filas de movimiento son la parte delicada: la descripción puede contener
guiones ('20461735283 - Francisco Calo Nottebohm', 'A una cuenta tuya -
Galicia'), y las columnas Débito/Crédito usan '-' cuando no aplican. Se
resuelve tomando los últimos 1-2 tokens de la línea como saldo, crédito y
débito (en ese orden, de derecha a izquierda: cada campo es '-' o un monto
'$ 1.234,56' / 'U$S 12,34'), y todo lo que sobra después de fecha+ref es la
descripción — sin importar cuántos guiones tenga adentro.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from ..models import AccountInfo, Movement, ParsedStatement, ParseError, parse_amount
from .base import register

_TIPO_RE = re.compile(r"^Tipo (.+?) Saldo Inicial (.+)$")
_MONEDA_RE = re.compile(r"^Moneda (.+?) Créditos (.+)$")
_CUIT_RE = re.compile(r"^CUIT (\d+) Débitos (.+)$")
_NUMERO_RE = re.compile(r"^Número (\S+)$")
_CBU_RE = re.compile(r"^CBU (\d+)$")
_IMP_RE = re.compile(r"^Imp\. Trans\. Financieras (.+?) Saldo Final (.+)$")
_ROW_PREFIX_RE = re.compile(r"^(\d{2}-\d{2}-\d{2}) (\d+) (.+)$")
_NUMBER_TOKEN_RE = re.compile(r"^-?\d{1,3}(\.\d{3})*(,\d{1,2})?$|^-?\d+(,\d{1,2})?$")


class _Block:
    def __init__(self) -> None:
        self.tipo = ""
        self.moneda = ""
        self.saldo_inicial = ""
        self.creditos_total = ""
        self.debitos_total = ""
        self.saldo_final = ""
        self.rows: list[tuple[Movement, Decimal]] = []  # (movimiento, saldo declarado)


def _period_from_pages(pages: list[str]) -> tuple[date, date] | None:
    m = re.search(r"(\d{1,2}) (\w{3}) (\d{4}) al (\d{1,2}) (\w{3}) (\d{4})", "\n".join(pages))
    if not m:
        return None
    months = {
        "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
    }
    d1, mo1, y1, d2, mo2, y2 = m.groups()
    return (
        date(int(y1), months[mo1.upper()], int(d1)),
        date(int(y2), months[mo2.upper()], int(d2)),
    )


def _currency_of(moneda: str) -> str:
    return "USD" if "USD" in moneda else "ARS"


def _parse_row(line: str) -> tuple[Movement, Decimal]:
    tokens = line.split()
    fields: list[str | None] = []
    for _ in range(3):  # saldo, crédito, débito — de derecha a izquierda
        if tokens[-1] == "-":
            fields.append(None)
            tokens = tokens[:-1]
        else:
            if len(tokens) < 2 or tokens[-2] not in ("$", "U$S"):
                raise ParseError(f"Brubank cuenta: monto inesperado en {line!r}")
            fields.append(f"{tokens[-2]} {tokens[-1]}")
            tokens = tokens[:-2]
    saldo_raw, credito_raw, debito_raw = fields
    if len(tokens) < 2:
        raise ParseError(f"Brubank cuenta: fila incompleta {line!r}")
    date_str, ref = tokens[0], tokens[1]
    description = " ".join(tokens[2:])
    if credito_raw:
        amount, currency = parse_amount(credito_raw), "USD" if "U$S" in credito_raw else "ARS"
    elif debito_raw:
        amount, currency = -parse_amount(debito_raw), "USD" if "U$S" in debito_raw else "ARS"
    else:
        raise ParseError(f"Brubank cuenta: fila sin crédito ni débito {line!r}")
    mv = Movement(date=datetime.strptime(date_str, "%d-%m-%y").date(), description=description, amount=amount, currency=currency, ref=ref)
    return mv, parse_amount(saldo_raw) if saldo_raw else Decimal(0)


class BrubankCuentaParser:
    name = "brubank_cuenta"

    def detect(self, pages: list[str]) -> bool:
        return bool(pages) and "Mi cuenta Resumen" in pages[0] and "Ciclo de facturación" not in pages[0]

    def parse(self, pages: list[str]) -> list[ParsedStatement]:
        lines = [ln.strip() for page in pages for ln in page.splitlines() if ln.strip()]
        period = _period_from_pages(pages)
        if period is None:
            raise ParseError("Brubank cuenta: no se encontró el período del resumen")

        blocks: list[_Block] = []
        current: _Block | None = None
        for line in lines:
            if line == "Mi cuenta Resumen":
                current = _Block()
                blocks.append(current)
                continue
            if current is None:
                continue
            if m := _TIPO_RE.match(line):
                current.tipo, current.saldo_inicial = m[1], m[2]
            elif m := _MONEDA_RE.match(line):
                current.moneda, current.creditos_total = m[1], m[2]
            elif m := _CUIT_RE.match(line):
                current.debitos_total = m[2]
            elif _NUMERO_RE.match(line) or _CBU_RE.match(line):
                pass
            elif m := _IMP_RE.match(line):
                current.saldo_final = m[2]
            elif line in ("Movimientos", "Sin Movimientos", "Fecha #Ref Descripción Débito Crédito Saldo"):
                pass
            elif _ROW_PREFIX_RE.match(line):
                current.rows.append(_parse_row(line))
            # cualquier otra línea (membrete repetido, dirección, legales) se ignora

        statements = [self._to_statement(b, *period) for b in blocks if b.rows]
        if not statements:
            raise ParseError("Brubank cuenta: no se encontró ninguna subcuenta con movimientos")
        return statements

    @staticmethod
    def _to_statement(block: _Block, period_start: date, period_end: date) -> ParsedStatement:
        currency = _currency_of(block.moneda)
        opening = parse_amount(block.saldo_inicial)
        closing = parse_amount(block.saldo_final)

        running = opening
        for mv, stated in block.rows:
            running += mv.amount
            if stated != running:
                raise ParseError(
                    f"Brubank cuenta ({block.tipo} {currency}): saldo corrido no cierra en "
                    f"{mv.date} {mv.description!r}: calculado {running}, extracto {stated}"
                )
        if running != closing:
            raise ParseError(f"Brubank cuenta ({block.tipo} {currency}): saldo final {running} != extracto {closing}")

        movements = [mv for mv, _ in block.rows]
        credits = sum((mv.amount for mv in movements if mv.amount > 0), Decimal(0))
        debits = sum((-mv.amount for mv in movements if mv.amount < 0), Decimal(0))
        expected_credits, expected_debits = parse_amount(block.creditos_total), parse_amount(block.debitos_total)
        if (credits, debits) != (expected_credits, expected_debits):
            raise ParseError(
                f"Brubank cuenta ({block.tipo} {currency}): totales no cierran: "
                f"créditos {credits} vs {expected_credits}, débitos {debits} vs {expected_debits}"
            )

        label = f"Brubank {block.tipo} ({currency})"
        product = block.tipo.strip().lower().replace(" ", "_")
        return ParsedStatement(
            account=AccountInfo(bank="Brubank", product=product, currency=currency, label=label),
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening,
            closing_balance=closing,
            movements=movements,
        )


register(BrubankCuentaParser())
