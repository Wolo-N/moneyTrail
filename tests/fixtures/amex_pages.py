"""Fixture sintética del Estado de Cuenta American Express: reproduce el
espacio errático que la extracción de texto mete en algunos montos justo
antes de los últimos 3 dígitos ('20 .000,00'), de forma inconsistente incluso
para el mismo importe repetido — no viene de nuestro código, es así en el
PDF real."""

PAGE_1 = """Corporate Services A Para consultas ingrese en
Estado de Cuenta
American Express Argentina SA
Titular Número de Cuenta Facturación Vencimiento
TITULAR DE PRUEBA 1111-222222-31000 05/07/26 14/07/26
Saldo Anterior $ Créditos $ Débitos $ Saldo a pagar $
100.000,00 100.000,00 50.000,00 Próximo Vencimiento Página 1 de 4
- + = 50.000,00 10/08/26
Fecha y detalle de las transacciones Importe en $
05 de Junio Gracias por su pago realizado en Banco Ejemplo S.A. 100.000,00
Socio: 1111-222222-31000 CR
Referencia 00260608
Fecha y detalle de las transacciones Importe en $
Nuevos Cargos en PESOS para TITULAR DE PRUEBA Importe en $
Número de cuenta 1111-222222-31000
03 de Junio RAPPI 111111111111 20 .000,00
Servicios Varios
Referencia 520677980 0 1
17 de Junio PARKING DE LAS ARTES 16482918 00:0 30.000,00
Productos/Servicios varios
Referencia 920821620 0 1"""

PAGE_2 = """Total de Cargos en PESOS para TITULAR DE PRUEBA 50.000,00
Fecha y detalle de las transacciones Importe en U$S
Total de Cargos en DOLARES para TITULAR DE PRUEBA 0,00"""

PAGES = [PAGE_1, PAGE_2]
