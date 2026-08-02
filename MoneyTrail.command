#!/bin/bash
# moneyTrail — lanzador para macOS: doble click y listo.
# La primera vez prepara el entorno (1-2 minutos); después abre directo.
cd "$(dirname "$0")"

pause_and_exit() {
    echo ""
    read -rp "Presioná Enter para cerrar..."
    exit 1
}

# (Los espacios en la ruta no son problema: Python genera los scripts del venv
# con un wrapper '#!/bin/sh' justamente para tolerarlos. Verificado.)

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
    if ! .venv/bin/python3 -m ensurepip --upgrade --default-pip > /tmp/moneytrail-ensurepip.log 2>&1; then
        cat /tmp/moneytrail-ensurepip.log
        echo ""
        if grep -qi "pyexpat" /tmp/moneytrail-ensurepip.log && grep -qi "Symbol not found" /tmp/moneytrail-ensurepip.log; then
            # Bug conocido: el Python de Homebrew queda con 'pyexpat' compilado
            # contra una libexpat que no tiene el símbolo que pip necesita para
            # importarse. No se arregla reinstalando pip: hay que resolverlo a
            # nivel de esa instalación de Python, así que no vale la pena
            # intentar el fallback de get-pip.py (va a fallar por lo mismo).
            echo "Esto es un bug conocido del Python de Homebrew en tu Mac: el módulo 'pyexpat'"
            echo "quedó compilado contra una libexpat que no tiene el símbolo que pip necesita"
            echo "para poder importarse. No es algo que se arregle reinstalando pip."
            echo ""
            echo "La forma más simple de resolverlo: instalá Python 3.13 (estable) desde"
            echo "https://www.python.org/downloads/ — es independiente de Homebrew, y moneyTrail"
            echo "lo va a preferir automáticamente la próxima vez, sin tocar nada más."
            echo ""
            echo "Si preferís seguir con el de Homebrew, probá en la terminal:"
            echo "  brew reinstall expat && brew reinstall python@3.14"
            rm -f /tmp/moneytrail-ensurepip.log
            pause_and_exit
        fi
        rm -f /tmp/moneytrail-ensurepip.log
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
