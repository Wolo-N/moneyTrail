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

## Estado

📋 En fase de planificación. Ver [PLAN.md](PLAN.md) para la arquitectura y el
plan de implementación completo.

## Principios

- **Local-first**: los PDFs y la base de datos nunca salen de tu máquina.
  El directorio `data/` está fuera del control de versiones.
- **Idempotente**: podés re-importar el mismo PDF las veces que quieras;
  los movimientos se deduplican.
- **Extensible**: cada banco es un parser aislado; agregar un banco nuevo
  no toca el resto del pipeline.
