#!/bin/bash
# moneyTrail — lanzador para Linux: doble click (o ./MoneyTrail.sh) y listo.
cd "$(dirname "$0")"

pause_and_exit() {
    echo ""
    read -rp "Presioná Enter para cerrar..."
    exit 1
}

# Python arma sus scripts internos (pip, ensurepip) con un '#!/ruta/al/python'
# en la primera línea; si esa ruta tiene un espacio, la ejecución se rompe y
# 'ensurepip'/pip fallan con errores crípticos. Lo detectamos antes de perder
# 2 minutos armando un venv que va a fallar igual.
case "$(pwd)" in
    *" "*)
        echo "Esta carpeta tiene un espacio en el nombre de alguna subcarpeta:"
        echo "  $(pwd)"
        echo ""
        echo "Python se rompe con espacios en la ruta al crear el entorno virtual."
        echo "Solución: renombrá o movés la carpeta del proyecto a una ruta sin espacios,"
        echo "por ejemplo ~/moneyTrail, y volvé a correr este archivo."
        pause_and_exit
        ;;
esac

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
    echo "moneyTrail necesita Python 3.11 o más nuevo, y no se encontró ninguna versión así."
    echo ""
    echo "Instalalo con el gestor de paquetes de tu distro (ej. 'sudo apt install python3.11')"
    echo "o desde https://www.python.org/downloads/ y volvé a correr este archivo."
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
