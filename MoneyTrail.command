#!/bin/bash
# moneyTrail — lanzador para macOS: doble click y listo.
# La primera vez prepara el entorno (1-2 minutos); después abre directo.
cd "$(dirname "$0")"

pause_and_exit() {
    echo ""
    read -rp "Presioná Enter para cerrar..."
    exit 1
}

# El Python del sistema en macOS suele ser 3.9 (o ni siquiera existir);
# moneyTrail necesita 3.11+. Buscamos una versión válida antes de crear el venv.
find_python() {
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        ver=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || continue
        major=${ver%%.*}
        minor=${ver#*.}
        if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python)" || {
    echo "moneyTrail necesita Python 3.11 o más nuevo, y no se encontró ninguna versión así en tu Mac."
    echo ""
    echo "Instalalo desde https://www.python.org/downloads/ (bajá el instalador para macOS,"
    echo "abrilo y seguí los pasos) y después volvé a hacer doble click en este archivo."
    pause_and_exit
}

# Si un intento anterior creó el venv con un Python viejo, la instalación
# falla y .venv/bin/moneytrail nunca llega a existir: lo recreamos desde cero.
if [ ! -x .venv/bin/moneytrail ]; then
    rm -rf .venv
    echo "Primera vez: preparando moneyTrail con $PYTHON (1-2 minutos)..."
    if ! "$PYTHON" -m venv .venv; then
        echo "No se pudo crear el entorno virtual."
        pause_and_exit
    fi
    .venv/bin/pip install --quiet --upgrade pip
    if ! .venv/bin/pip install --quiet -e .; then
        echo "La instalación falló. Revisá el mensaje de arriba."
        pause_and_exit
    fi
fi

echo "Abriendo moneyTrail en tu navegador..."
.venv/bin/moneytrail gui || pause_and_exit
