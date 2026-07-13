"""Fixture sintética del resumen de cuenta Brubank: tres subcuentas en un
mismo documento (caja de ahorro ARS, cuenta remunerada vacía, caja de ahorro
USD), con la tabla de movimientos de la primera cuenta partida entre dos
páginas — igual que el PDF real — para ejercitar la continuación entre
páginas y el descarte de la subcuenta sin movimientos."""

PAGE_1 = """1 JUN 2026 al 30 JUN 2026
Titular De Prueba
Calle Falsa 123
B0000ZZZ CIUDAD
Mi cuenta Resumen
Tipo Caja de ahorro Saldo Inicial $ 100.000,00
Moneda Pesos (ARS) Créditos $ 50.000,00
CUIT 20111111111 Débitos $ 30.000,00
Número 1000000001
CBU 1430000000000000000001
Imp. Trans. Financieras $ 0,00 Saldo Final $ 120.000,00
Movimientos
Fecha #Ref Descripción Débito Crédito Saldo
01-06-26 2000000001 A una cuenta tuya - Galicia $ 20.000,00 - $ 80.000,00
01-06-26 2000000002 20461735283 - Juan Perez - $ 50.000,00 $ 130.000,00"""

PAGE_2 = """1 JUN 2026 al 30 JUN 2026
Titular De Prueba
Calle Falsa 123
Movimientos
Fecha #Ref Descripción Débito Crédito Saldo
05-06-26 2000000003 Pago de tarjeta de crédito $ 10.000,00 - $ 120.000,00
Mi cuenta Resumen
Tipo Cuenta remunerada Saldo Inicial $ 0,00
Moneda Pesos (ARS) Créditos $ 0,00
CUIT 20111111111 Débitos $ 0,00
Imp. Trans. Financieras $ 0,00 Saldo Final $ 0,00
Sin Movimientos
Mi cuenta Resumen
Tipo Caja de ahorro Saldo Inicial U$S 10,00
Moneda Dólar (USD) Créditos U$S 20,00
CUIT 20111111111 Débitos U$S 5,00
Número 1000000002
CBU 1430000000000000000002
Imp. Trans. Financieras U$S 0,00 Saldo Final U$S 25,00
Movimientos
Fecha #Ref Descripción Débito Crédito Saldo
02-06-26 2000000004 De una cuenta tuya - Galicia - U$S 20,00 U$S 30,00
03-06-26 2000000005 Pago de tarjeta de crédito U$S 5,00 - U$S 25,00"""

PAGES = [PAGE_1, PAGE_2]
