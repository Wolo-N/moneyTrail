#!/bin/bash
# moneyTrail — lanzador para Linux: doble click (o ./MoneyTrail.sh) y listo.
cd "$(dirname "$0")"

pause_and_exit() {
    echo ""
    read -rp "Presioná Enter para cerrar..."
    exit 1
}

# (Los espacios en la ruta no son problema: Python genera los scripts del venv
# con un wrapper '#!/bin/sh' justamente para tolerarlos. Verificado.)

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

# El venv sirve sólo si además de existir, funciona: guarda rutas absolutas
# adentro, así que mover la carpeta lo rompe ('bad interpreter'). También queda
# inservible si un intento anterior falló a mitad o si desapareció el Python
# con el que se creó. En cualquiera de esos casos se rearma solo.
# Se comprueba ejecutando el comando de verdad (~1 s): el script tiene grabada
# la ruta absoluta del venv en su shebang, y 'python3' adentro es un symlink
# relativo que sigue resolviendo aunque la carpeta se haya movido — o sea que
# mirar el intérprete no alcanza para detectar que está roto.
venv_ok() {
    [ -x .venv/bin/moneytrail ] && .venv/bin/moneytrail --help > /dev/null 2>&1
}

if ! venv_ok; then
    if [ -d .venv ]; then
        echo "El entorno quedó desactualizado (¿moviste la carpeta?). Rearmándolo..."
    else
        echo "Primera vez: preparando moneyTrail con $PYTHON (1-2 minutos)..."
    fi
    rm -rf .venv

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
