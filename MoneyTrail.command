#!/bin/bash
# moneyTrail — lanzador para macOS: doble click y listo.
# La primera vez prepara el entorno (1-2 minutos); después abre directo.
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
        echo "por ejemplo ~/moneyTrail (podés sacar el espacio de 'Proyectos Personales'"
        echo "o mover moneyTrail directo al home), y volvé a hacer doble click acá."
        pause_and_exit
        ;;
esac

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

    # Creamos el venv SIN pip y lo instalamos nosotros a continuación: cuando
    # 'python -m venv' hace este paso solo, si ensurepip falla oculta el error
    # real detrás de un mensaje genérico ('returned non-zero exit status 1',
    # sin más detalle). Separándolo en dos pasos vemos la causa de verdad.
    if ! "$PYTHON" -m venv --without-pip .venv; then
        echo "No se pudo crear el entorno virtual."
        pause_and_exit
    fi
    if ! .venv/bin/python3 -m ensurepip --upgrade --default-pip; then
        echo ""
        echo "ensurepip falló (ver el error de arriba). Probando instalar pip de otra forma..."
        if ! curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/moneytrail-get-pip.py; then
            echo "No se pudo descargar pip. Revisá tu conexión a internet e intentá de nuevo."
            pause_and_exit
        fi
        if ! .venv/bin/python3 /tmp/moneytrail-get-pip.py --quiet; then
            echo "Tampoco se pudo instalar pip así. Mandá el error de arriba para diagnosticarlo."
            pause_and_exit
        fi
        rm -f /tmp/moneytrail-get-pip.py
    fi
    .venv/bin/pip install --quiet --upgrade pip
    if ! .venv/bin/pip install --quiet -e .; then
        echo "La instalación falló. Revisá el mensaje de arriba."
        pause_and_exit
    fi
fi

echo "Abriendo moneyTrail en tu navegador..."
.venv/bin/moneytrail gui || pause_and_exit
