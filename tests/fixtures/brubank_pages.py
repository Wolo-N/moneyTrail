"""Fixture sintética del resumen de tarjeta Brubank: datos inventados,
subtotales y totales consistentes."""

PAGE_1 = """Titular De Prueba
Calle Falsa 123
Ciclo de facturación
1 jun 8 jun 1 jul 6 jul 1 ago 6 ago
Cierre anterior Vencimiento anterior Cierre actual Vencimiento actual Próximo cierre Próximo vencimiento
Balance total pesos Balance total dólares
$ 31.210,00 U$S 20,00
Límites
Crédito $ 404.000 Adelanto $ 80.800
Total en dólares Total en pesos
Movimientos
U$S 20,00 $ 30.000,00
Tarjeta 1111 T Prueba Subtotal: U$S 20,00 $ 30.000,00
Fecha #Ref Descripción Dólares Pesos
2026-06-01 1000000001 Rappi $ 20.000,00
2026-06-03 1000000002 Anthropic* Claude Sub U$S 20,00
2026-06-10 1000000003 Disney Plus $ 10.000,00"""

PAGE_2 = """Si hiciste gastos en dólares, podés pagarlos con USD antes del vencimiento.
Total
Comisiones
$
1.000,00
Fecha #Ref Descripción Pesos
2026-06-04 1000000004 Pago de comisión por plan Brubank $ 1.000,00
Total
Intereses
$ 0,00
Fecha #Ref Descripción Pesos
Impuestos
de todas tus tarjetas
Los impuestos por utilizar la tarjeta de crédito están sujetos a las regulaciones del Banco Central.
Descripción Pesos
IVA $ 210,00
Total $ 210,00
Cuotas a vencer
de todas tus tarjetas
Fecha Pesos
2026-08 $ 0
Pagos
Fecha Valor
2026-06-01 $ 15.000,00
2026-06-16 $ 6.000,00
Total $ 21.000,00
Pago en dólares
Fecha Valor
2026-06-01 U$S 5,00
Total U$S 5,00
Tasas
TNA TEA TEM CFTEA CFTNA"""

PAGES = [PAGE_1, PAGE_2]
