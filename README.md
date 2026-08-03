# moneyTrail

Rastreá a dónde va la plata que entra a tus cuentas.

moneyTrail lee los PDFs de tus resúmenes bancarios y de tarjeta, normaliza los
movimientos, concilia las transferencias entre tus propias cuentas (para no
contar la plata dos veces), aprende a categorizar tus gastos con un click y te
muestra el flujo completo: **ingresos → cuentas → categorías**.

Todo corre en tu máquina. Los PDFs y la base de datos nunca salen de ahí.

---

## El ritual mensual (2 minutos)

La app te lo recuerda sola en el panel **"Tu próximo paso"**, así que no hace
falta memorizar nada:

1. **Soltá los PDFs.** Descargá del homebanking los resúmenes del mes (banco y
   tarjetas) y arrastralos a la app. Podés soltar varios juntos y repetir
   archivos sin miedo: nunca se duplica nada.
2. **Categorizá lo que aparezca pendiente**, con un click. Cada elección queda
   aprendida y no vuelve a preguntarte por ese comercio.
3. **Mirá el flujo y las tendencias.** Listo.

Si te olvidás de importar algo, la app te lo dice: sabe qué cuentas tenés, hasta
qué mes llega cada una y cuáles te faltan.

## Instalación

Requisito único: [Python 3.11+](https://www.python.org/downloads/) (en Windows,
marcá "Add Python to PATH" al instalarlo).

Doble click en el lanzador de tu sistema — la primera vez prepara el entorno solo
(1-2 minutos) y después abre directo en el navegador:

| Sistema | Lanzador |
|---|---|
| Windows | `MoneyTrail.bat` |
| macOS | `MoneyTrail.command` (la primera vez: click derecho → Abrir) |
| Linux | `MoneyTrail.sh` |

Podés tener la carpeta donde te quede cómodo (Escritorio, Documentos, el home),
con espacios o acentos en la ruta: no afecta.

## Qué te muestra

| Sección | Qué responde |
|---|---|
| **Resumen** | ¿A dónde fue la plata? Diagrama de flujo (Sankey) clickeable: tocás cualquier nodo y ves las transacciones exactas que lo componen. |
| **Tendencias** | ¿Cómo vengo mes a mes? Ingresos vs gastos, resultado de cada mes y en qué categorías se va la plata a lo largo del tiempo. |
| **Categorías** | ¿En qué gasto y qué cambió? Ranking con porcentajes, comparación contra el mes anterior, los gastos más grandes y los comercios donde más gastás. |
| **Suscripciones** | ¿Qué pago todos los meses? Streaming, software y abonos detectados solos, con su costo mensual y anual, los aumentos silenciosos, y cuáles no tienen cargos recientes (por si diste de baja). Abajo, los hábitos que se repiten como delivery o transporte. |
| **Movimientos** | Buscador libre sobre todo, con filtros por categoría y cuenta, y exportación a CSV. |

Un detalle que importa: los meses a los que les falta algún resumen aparecen
**rayados** y quedan fuera de los promedios. Un mes sin el extracto donde entra
el sueldo parece un desastre financiero y no lo es.

## Categorización

- Un click en una categoría crea la regla y la aplica a todo el histórico.
- La app **sugiere** (chip destacado con ★) cuando reconoce el comercio de antes
  o cuando el movimiento parece una transferencia a una persona.
- Si te equivocaste, **Deshacer** en el aviso que aparece abajo.
- Si volvés a clasificar un comercio, tu última decisión gana.

Las reglas que creás desde la app viven en `rules/learned.yaml` (podés editarlas
a mano). Las curadas por vos, en [`rules/categories.yaml`](rules/categories.yaml):
regex en orden, la primera que matchea gana, y pueden además redefinir el tipo de
movimiento (por ejemplo marcar algo como transferencia interna para que no cuente
como gasto).

## Bancos soportados

| Banco | Producto | Parser |
|---|---|---|
| Banco Galicia | Cuentas (caja de ahorro, cuenta corriente, ARS + USD) | `galicia_caja_ahorro` |
| Banco Galicia | Tarjeta de crédito VISA (ARS + USD) | `galicia_visa` |
| Brubank | Resumen de cuenta (ARS + USD, multi-subcuenta) | `brubank_cuenta` |
| Brubank | Tarjeta de crédito (ARS + USD) | `brubank_tarjeta` |
| American Express | Tarjeta corporativa | `amex_tarjeta` |

Los parsers reconocen los resúmenes por su **estructura**, no por el nombre del
producto: una cuenta nueva del mismo banco entra sola, sin escribir código. Si
aun así un PDF no se reconoce, la app te dice qué encontró adentro (y si es un
escaneo sin texto) para que se pueda agregar el soporte; el archivo queda
guardado en `data/inbox/`.

Agregar un banco es escribir un parser en `src/moneytrail/parsers/` y
registrarlo; el resto del pipeline no se toca.

Cada import **valida que los saldos del PDF cierren** (saldo inicial +
movimientos = saldo final, subtotales por tarjeta, totales declarados). Si un
banco cambia el formato, el import falla con el detalle en vez de guardar datos
incompletos en silencio.

## Línea de comandos

La app y la CLI comparten el mismo pipeline.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

.venv/bin/moneytrail gui                      # la app de escritorio
.venv/bin/moneytrail import data/inbox/       # importar (idempotente)
.venv/bin/moneytrail status                   # qué hay cargado y qué falta
.venv/bin/moneytrail categorize --review      # revisar lo no categorizado
.venv/bin/moneytrail report --from 2026-04 --to 2026-06 --usd-rate 1405 --open
```

## Cómo está hecho

Pipeline local de seis etapas sobre SQLite: **ingesta → parseo → normalización →
conciliación → categorización → reporte**. Arquitectura y decisiones de diseño
en [PLAN.md](PLAN.md).

Dos garantías que sostienen la experiencia:

- **Nada se duplica.** Hash por archivo y por movimiento: re-importar un PDF, o
  extractos consolidados con períodos solapados, es un no-op.
- **Nada se traba.** Las lecturas caras se cachean contra una versión de datos
  que sólo cambia al escribir, y guardar una categoría devuelve el estado nuevo
  completo en un solo request. Un click responde en decenas de milisegundos.

```bash
.venv/bin/python -m pytest      # 144 tests, con fixtures sintéticas
```

Las fixtures de test son sintéticas: no hay datos personales en el repositorio,
y `data/` está en `.gitignore` desde el primer commit.
