"""Fixture sintética del resumen VISA de Banco Galicia.

Este formato se parsea por coordenadas (pesos y dólares son dos columnas
distintas), así que la fixture define cada fila como pares `(texto, x0)` y
un helper arma las palabras con `x1` y `top` como haría pdfplumber.

Las X salen del layout real: descripción en 86, comprobante en 364, importe
en pesos terminando en ~494 y en dólares en ~580.
"""

# Coordenadas de referencia por columna
X_DATE, X_MARKER, X_DESC, X_VOUCHER = 23, 74, 86, 366
X_ARS_END, X_USD_END = 494, 580


def _row(top, cells):
    """cells: [(texto, x0)] o [(texto, x0, x1)] cuando importa el borde derecho."""
    words = []
    for cell in cells:
        text, x0 = cell[0], cell[1]
        x1 = cell[2] if len(cell) > 2 else x0 + len(text) * 5.2
        words.append({"text": text, "x0": float(x0), "x1": float(x1), "top": float(top)})
    return words


def ars(text):
    """Importe en la columna de pesos (alineado a la derecha en 494)."""
    return (text, X_ARS_END - len(text) * 5.2, X_ARS_END)


def usd(text):
    """Importe en la columna de dólares (alineado a la derecha en 580)."""
    return (text, X_USD_END - len(text) * 5.2, X_USD_END)


PAGE_1_TEXT = """Resumen N° VI00000000009999999
Tarjeta Crédito VISA
TITULAR DE PRUEBA Consumidor Final CUIT Banco: 30-50000173-5
02-Jul-26 13-Jul-26 30-Jul-26 07-Ago-26 27-Ago-26 04-Sep-26
CONSOLIDADO PESOS DÓLARES
SALDO ANTERIOR 100.000,00 0,00
07-07-26 SU PAGO EN PESOS -100.000,00
DETALLE DEL CONSUMO
FECHA REFERENCIA CUOTA COMPROBANTE PESOS DÓLARES
03-07-26 K JUMBO PACHECO 196227 20.000,00
04-07-26 K KFC Ruta 202 854027 30.000,00
TARJETA 9796 Total Consumos de TITULAR DE PRUEBA 50.000,00 0,00
10-07-26 * ZULU HAUS 080173 15.000,00
12-07-26 K SERVICIO EXTERIOR 004809 25,50
TARJETA 0905 Total Consumos de TITULAR DE PRUEBA 15.000,00 25,50
30-07-26 IMPUESTO DE SELLOS $ 1.000,00
TOTAL A PAGAR 66.000,00 25,50"""

PAGE_1_WORDS = (
    _row(100, [("SALDO", X_DESC), ("ANTERIOR", 116), ars("100.000,00"), usd("0,00")])
    + _row(115, [("07-07-26", X_DATE), ("SU", X_DESC), ("PAGO", 100), ("EN", 124), ("PESOS", 137),
                 ars("-100.000,00")])
    + _row(140, [("03-07-26", X_DATE), ("K", X_MARKER), ("JUMBO", X_DESC), ("PACHECO", 117),
                 ("196227", X_VOUCHER), ars("20.000,00")])
    + _row(155, [("04-07-26", X_DATE), ("K", X_MARKER), ("KFC", X_DESC), ("Ruta", 104), ("202", 124),
                 ("854027", X_VOUCHER), ars("30.000,00")])
    + _row(170, [("TARJETA", X_DESC), ("9796", 126), ("Total", 148), ("Consumos", 170), ("de", 214),
                 ("TITULAR", 226), ars("50.000,00"), usd("0,00")])
    + _row(185, [("10-07-26", X_DATE), ("*", X_MARKER), ("ZULU", X_DESC), ("HAUS", 110),
                 ("080173", X_VOUCHER), ars("15.000,00")])
    # Consumo en dólares: en texto plano sería indistinguible de uno en pesos
    + _row(200, [("12-07-26", X_DATE), ("K", X_MARKER), ("SERVICIO", X_DESC), ("EXTERIOR", 130),
                 ("004809", X_VOUCHER), usd("25,50")])
    + _row(215, [("TARJETA", X_DESC), ("0905", 126), ("Total", 148), ("Consumos", 170), ("de", 214),
                 ("TITULAR", 226), ars("15.000,00"), usd("25,50")])
    + _row(230, [("30-07-26", X_DATE), ("IMPUESTO", X_DESC), ("DE", 130), ("SELLOS", 143), ("$", 191),
                 ars("1.000,00")])
    + _row(245, [("TOTAL", 38), ("A", 70), ("PAGAR", 79), ars("66.000,00"), usd("25,50")])
)

PAGES = [PAGE_1_TEXT]
WORDS = [PAGE_1_WORDS]
