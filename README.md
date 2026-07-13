# moneyTrail

Rastreá a dónde va la plata que entra a tus cuentas.

moneyTrail ingiere los PDFs de extractos bancarios y resúmenes de tarjeta, normaliza
los movimientos en un modelo único, concilia las transferencias entre tus propias
cuentas (para no contar la plata dos veces), categoriza los gastos y genera un
**diagrama de Sankey** que muestra el flujo: ingresos → cuentas → categorías de gasto.

```
Sueldo ──────┐
             ├──> Caja de ahorro ──> Tarjeta ──> Delivery / Suscripciones / ...
Reintegros ──┘                  └──> Débito  ──> Supermercado / Transporte / ...
```

Formatos soportados hoy: **Banco Galicia** (caja de ahorro en pesos) y
**Brubank** (resumen de tarjeta de crédito, ARS + USD). Agregar un banco es
escribir un parser nuevo en `src/moneytrail/parsers/` y registrarlo.

## Modo aplicación (recomendado, sin terminal)

Requisito único: tener [Python 3.11+](https://www.python.org/downloads/) instalado
(en Windows, marcá "Add Python to PATH" al instalarlo).

1. Descargá o cloná este repo.
2. Doble click en el lanzador de tu sistema:
   - **Windows** → `MoneyTrail.bat`
   - **macOS** → `MoneyTrail.command` (la primera vez: click derecho → Abrir)
   - **Linux** → `MoneyTrail.sh`
3. La primera vez prepara el entorno solo (1-2 minutos). Después se abre la app
   en tu navegador: arrastrás los PDFs, categorizás lo que falte con un click y
   generás el reporte. Todo corre en `127.0.0.1` — nada sale de tu máquina.

Para cerrar la app, cerrá la ventana de terminal que queda abierta de fondo.

## Uso por línea de comandos

Instalación:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

```bash
# 1. Dejá tus PDFs en data/inbox/ e importalos (idempotente: re-importar no duplica)
moneytrail import data/inbox/

# 2. Mirá qué hay cargado y qué falta
moneytrail status

# 3. Revisá lo que quedó sin categorizar y agregá reglas a rules/categories.yaml
moneytrail categorize --review

# 4. Generá el reporte con el Sankey (el tipo de cambio aplica a los consumos en USD)
moneytrail report --from 2026-04 --to 2026-06 --usd-rate 1405 --open
```

El reporte es un HTML auto-contenido (funciona offline) con el diagrama de flujo,
gasto por categoría, movimientos sin categorizar y flujos internos sin conciliar.

Cada import valida que los saldos del PDF cierren (saldo inicial + movimientos =
saldo final, subtotales por tarjeta): si un banco cambia el formato, el import
falla con detalle en vez de guardar datos incompletos.

## Categorización

Las reglas viven en [`rules/categories.yaml`](rules/categories.yaml): regex en
orden, la primera que matchea gana. Cada regla puede asignar `category` (nivel
`Top/Sub`) y/o redefinir `kind` (p. ej. marcar `TRANSF. CTAS PROPIAS` como flujo
interno para que no cuente como gasto).

## Principios

- **Local-first**: los PDFs y la base de datos nunca salen de tu máquina.
  El directorio `data/` está fuera del control de versiones.
- **Idempotente**: re-importar el mismo PDF (o extractos consolidados con
  períodos solapados) no genera duplicados.
- **Montos exactos**: `Decimal` en todo el pipeline, nunca floats.

## Desarrollo

```bash
.venv/bin/python -m pytest        # tests con fixtures sintéticas (sin datos reales)
```

Arquitectura y decisiones de diseño: [PLAN.md](PLAN.md).
