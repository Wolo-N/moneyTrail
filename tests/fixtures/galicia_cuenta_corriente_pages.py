"""Fixture sintética de una Cuenta Corriente de Galicia.

Mismo layout que la caja de ahorro pero otro producto en el título — y sin
movimientos, que es como llegan las cuentas que no se usan. Sirve para fijar
que el parser detecta por estructura y no por el nombre del producto.
"""

PAGE_1 = """Resumen de Cuenta Corriente en Pesos
PERSONA DE PRUEBA CUIL del Responsable Impositivo : 20-11111111-1
IVA: Consumidor Final
Cantidad de cotitulares: 0
Datos de la cuenta Período de movimientos Saldos
Tipo de cuenta
Cuenta Corriente en Pesos
$0,00
Número de cuenta
N° 0008041-1 313-1
$0,00
CBU 06/05/2026 05/06/2026
0070313820000008041119
Disponés de 30 días desde la recepción para cuestionar este resumen.
El monto de IVA discriminado no puede computarse como crédito fiscal.
Tasa Extraordinaria sobre Saldos Deudores (excedidos y transitorios): 137,50% T.N.A.
Movimientos
Fecha Descripción Origen Crédito Débito Saldo
Sin Movimientos
Los depósitos en pesos y en moneda extranjera cuentan con la garantía de hasta $25.000.000.
Resumen de Cuenta Corriente en Pesos Página 1 / 1
20260605049040385P"""

# Cuenta corriente con movimientos, para verificar que no es sólo el caso vacío
PAGE_WITH_MOVEMENTS = """Resumen de Cuenta Corriente en Pesos
PERSONA DE PRUEBA CUIL del Responsable Impositivo : 20-11111111-1
Datos de la cuenta Período de movimientos Saldos
Tipo de cuenta
Cuenta Corriente en Pesos
$50.000,00
Número de cuenta
N° 0008041-1 313-1
$35.000,00
CBU 06/05/2026 05/06/2026
0070313820000008041119
Disponés de 30 días desde la recepción para cuestionar este resumen.
Movimientos
Fecha Descripción Origen Crédito Débito Saldo
10/05/26 COMPRA DEBITO 0783 -15.000,00 35.000,00
PROVEEDOR EJEMPLO
4511111111111111
Total $ 0,00 -$ 15.000,00 $ 35.000,00
Resumen de Cuenta Corriente en Pesos Página 1 / 1
20260605049040385P"""

PAGES = [PAGE_1]
PAGES_WITH_MOVEMENTS = [PAGE_WITH_MOVEMENTS]
