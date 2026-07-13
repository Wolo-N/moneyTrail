#!/bin/bash
# moneyTrail — lanzador para macOS: doble click y listo.
# La primera vez prepara el entorno (1-2 minutos); después abre directo.
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
