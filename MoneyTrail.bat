@echo off
rem moneyTrail — lanzador para Windows: doble click y listo.
rem La primera vez prepara el entorno (1-2 minutos); despues abre directo.
cd /d "%~dp0"

if not exist ".venv\Scripts\moneytrail.exe" (
    echo Primera vez: preparando moneyTrail ^(1-2 minutos^)...
    where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
    if errorlevel 1 (
        echo.
        echo No se encontro Python. Instalalo desde https://www.python.org/downloads/
        echo y marca "Add Python to PATH" durante la instalacion.
        pause
        exit /b 1
    )
    .venv\Scripts\pip install --quiet --upgrade pip
    .venv\Scripts\pip install --quiet -e .
)

echo Abriendo moneyTrail en tu navegador...
.venv\Scripts\moneytrail gui
pause
