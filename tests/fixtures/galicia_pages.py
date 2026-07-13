"""Fixture sintética del extracto Galicia: misma estructura que el PDF real,
datos inventados, saldos consistentes."""

PAGE_1 = """Resumen de Caja de Ahorro en Pesos
PERSONA DE PRUEBA CUIL del Responsable Impositivo : 20-11111111-1
IVA: Consumidor Final
Cantidad de cotitulares: 0
Datos de la cuenta Período de movimientos Saldos
Tipo de cuenta
Caja de Ahorro en Pesos
$100.000,00
Número de cuenta
N° 1234567-8 999-9
$150.006,67
CBU 01/04/2026 30/04/2026
0070000000000000000000
Disponés de 30 días desde la recepción para cuestionar este resumen.
Movimientos
Fecha Descripción Origen Crédito Débito Saldo
05/04/26 SNP PAGO A PROVEEDORES 80.000,00 180.000,00
EMPRESA EJEMPLO
30111111119
CITIBANK N.A.
07/04/26 COMPRA DEBITO 0783 -21.000,00 159.000,00
PLAYAS SUBTERRANEAS
4511111111111111
10/04/26 TRANSF. CTAS PROPIAS -50.000,00 109.000,00
CU 20111111111
14300000000000000000
BBNK
4511111111111111
VARIOS
Resumen de Caja de Ahorro en Pesos Página 1 / 2
20260101000000000P"""

PAGE_2 = """Resumen de Caja de Ahorro en Pesos
Fecha Descripción Origen Crédito Débito Saldo
12/04/26 INTERES CAPITALIZADO 6,67 109.006,67
Abril 2026
15/04/26 TRANSFERENCIAS CASH 62.000,00 171.006,67
SUELDOS
EMPRESA EJEMPLO S
30111111119
CITIBANK N.A.
20/04/26 PAGO TARJETA VISA -21.000,00 150.006,67
Total $ 142.006,67 -$ 92.000,00 $ 150.006,67
Los depósitos en pesos y en moneda extranjera cuentan con la garantía de hasta $25.000.000.
Resumen de Caja de Ahorro en Pesos Página 2 / 2
20260101000000000P"""

PAGES = [PAGE_1, PAGE_2]
