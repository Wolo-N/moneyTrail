from . import (  # noqa: F401  (importarlos los registra)
    amex_tarjeta,
    brubank_cuenta,
    brubank_tarjeta,
    galicia_caja_ahorro,
    galicia_visa,
)
from .base import find_parser

__all__ = ["find_parser"]
