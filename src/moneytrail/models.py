"""Modelo canónico compartido por todas las etapas del pipeline."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Kind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER_INTERNAL = "transfer_internal"
    CARD_PAYMENT = "card_payment"
    TAX = "tax"
    FEE = "fee"
    INTEREST = "interest"
    FX = "fx"  # compra/venta de moneda extranjera


class AccountInfo(BaseModel):
    bank: str
    product: str  # 'caja_ahorro' | 'tarjeta_credito'
    currency: str  # moneda principal de la cuenta
    label: str  # nombre para mostrar, único por cuenta


class Movement(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: date
    description: str  # primera línea del movimiento
    detail: str = ""  # líneas de continuación (contraparte, CUIT, banco...)
    counterparty: str = ""
    amount: Decimal  # + crédito / − débito, en la moneda original
    currency: str = "ARS"
    ref: str = ""  # #Ref u otro identificador provisto por el banco
    kind: Kind | None = None  # el parser puede fijarlo; si no, se infiere del signo


class ParsedStatement(BaseModel):
    account: AccountInfo
    period_start: date
    period_end: date
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    movements: list[Movement]


class ParseError(Exception):
    """El PDF se reconoció pero el contenido no valida (saldos que no cierran, etc.)."""


_AMOUNT_RE = re.compile(r"^-?\d{1,3}(\.\d{3})*(,\d{1,2})?$|^-?\d+(,\d{1,2})?$")


def parse_amount(raw: str) -> Decimal:
    """Convierte un monto en formato argentino ('1.234,56', '-21.000,00') a Decimal.

    Acepta prefijos '$' y 'U$S' y espacios intermedios.
    """
    s = raw.strip().replace("U$S", "").replace("$", "").replace(" ", "")
    if not _AMOUNT_RE.match(s):
        raise InvalidOperation(f"Monto no reconocido: {raw!r}")
    return Decimal(s.replace(".", "").replace(",", "."))


def dedupe_hash(account_label: str, mv: Movement) -> str:
    """Hash estable por movimiento: re-importar el mismo PDF (o períodos
    solapados de extractos consolidados) no genera duplicados."""
    desc_norm = re.sub(r"\s+", " ", (mv.description + " " + mv.detail).upper()).strip()
    parts = [account_label, mv.date.isoformat(), str(mv.amount), mv.currency, desc_norm, mv.ref]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
