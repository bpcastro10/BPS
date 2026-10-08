@echo off
rem ============================================================================
rem  Instala TODO lo necesario (solo la primera vez) y levanta la PoC de cheques:
rem  detector de firmas + busqueda de campos + PaddleOCR + GLM-OCR + interfaz web.
rem  Todo corre en un solo proceso local en http://127.0.0.1:8300
rem ============================================================================
setlocal
cd /d "%~dp0"
title PoC cheques - instalacion y arranque

rem --- 1. Python 3.10 o superior (si falta, se instala con winget) -------------
set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
    echo Python no esta instalado. Instalando Python 3.11 con winget...
    winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERROR] No se pudo instalar Python. Instalalo desde https://www.python.org ^(marca "Add to PATH"^) y vuelve a ejecutar.
        goto :error
    )
    set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
"%PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || (echo [ERROR] Se necesita Python 3.10 o superior. & goto :error)

rem --- 2. Entorno virtual y librerias -----------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    "%PY%" -m venv .venv || goto :error
)
if not exist ".venv\.instalado" (
    echo Instalando librerias ^(la primera vez tarda varios minutos^)...
    .venv\Scripts\python -m pip install --upgrade pip -q
    .venv\Scripts\python -m pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu || goto :error
    .venv\Scripts\python -m pip install -r requirements.txt || goto :error
    echo ok> .venv\.instalado
) else (
    echo Librerias ya instaladas.
)

rem --- 3. Modelos (GLM-OCR 2,5 GB y PaddleOCR; el de firmas ya viene incluido) --
.venv\Scripts\python descargar_modelos.py || goto :error

rem --- 4. Levantar: se cierra el servicio anterior si estaba corriendo ---------
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8300" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>nul
echo.
echo Levantando la PoC ^(cargar los modelos tarda 1-2 minutos^)...
echo Primero se pregunta CPU o GPU y cuantos procesos ^(Enter = recomendado^).
echo Cuando diga "Abrir http://127.0.0.1:8300" se abre el navegador. Para apagar: cierra esta ventana.
.venv\Scripts\python servidor.py --abrir-navegador
goto :fin

:error
echo.
echo Hubo un error. Revisa el mensaje de arriba.
:fin
pause
