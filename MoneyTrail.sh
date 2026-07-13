#!/bin/bash
# moneyTrail — lanzador para Linux: doble click (o ./MoneyTrail.sh) y listo.
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/moneytrail ]; then
    echo "Primera vez: preparando moneyTrail (1-2 minutos)..."
    python3 -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -e .
fi

echo "Abriendo moneyTrail en tu navegador..."
exec .venv/bin/moneytrail gui
