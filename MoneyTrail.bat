@echo off
setlocal enabledelayedexpansion
rem moneyTrail — lanzador para Windows: doble click y listo.
cd /d "%~dp0"

set PYTHON=

rem Probamos el "py launcher" pidiendo versiones 3.11+ especificamente, y despues
rem "python"/"python3" a secas, validando que sean 3.11+ (Windows suele traer
rem versiones viejas o ninguna).
for %%V in (3.13 3.12 3.11) do (
    if "!PYTHON!"=="" (
        py -%%V -c "" >nul 2>nul && set PYTHON=py -%%V
    )
)
if "!PYTHON!"=="" (
    for %%C in (python python3) do (
        if "!PYTHON!"=="" (
            where %%C >nul 2>nul && (
                for /f "delims=" %%O in ('%%C -c "import sys; print(1 if sys.version_info[:2]>=(3,11) else 0)" 2^>nul') do (
                    if "%%O"=="1" set PYTHON=%%C
                )
            )
        )
    )
)

if "!PYTHON!"=="" (
    echo moneyTrail necesita Python 3.11 o mas nuevo, y no se encontro ninguna version asi.
    echo.
    echo Instalalo desde https://www.python.org/downloads/
    echo Durante la instalacion, marca la casilla "Add python.exe to PATH".
    echo Despues volve a hacer doble click en este archivo.
    pause
    exit /b 1
)

rem El venv sirve solo si ademas de existir, funciona: guarda rutas absolutas
rem adentro, asi que mover la carpeta lo rompe. Tambien queda inservible si un
rem intento anterior fallo a mitad. En esos casos se rearma solo.
rem Se comprueba ejecutando el comando de verdad: el lanzador del venv tiene
rem grabada su ruta absoluta, asi que mover la carpeta lo rompe aunque el
rem archivo siga ahi.
set VENV_OK=
if exist ".venv\Scripts\moneytrail.exe" (
    .venv\Scripts\moneytrail.exe --help >nul 2>nul && set VENV_OK=1
)
if not defined VENV_OK (
    if exist ".venv" (
        echo El entorno quedo desactualizado ^(^¿moviste la carpeta?^). Rearmandolo...
        rmdir /s /q ".venv"
    ) else (
        echo Primera vez: preparando moneyTrail con !PYTHON! ^(1-2 minutos^)...
    )
    !PYTHON! -m venv .venv
    if errorlevel 1 (
        echo No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
    .venv\Scripts\pip install --quiet --upgrade pip
    .venv\Scripts\pip install --quiet -e .
    if errorlevel 1 (
        echo La instalacion fallo. Revisa el mensaje de arriba.
        pause
        exit /b 1
    )
)

echo Abriendo moneyTrail en tu navegador...
.venv\Scripts\moneytrail gui
pause
