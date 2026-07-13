from . import amex_tarjeta, brubank_cuenta, brubank_tarjeta, galicia_caja_ahorro  # noqa: F401  (registran los parsers)
from .base import find_parser

__all__ = ["find_parser"]
