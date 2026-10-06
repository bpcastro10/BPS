@echo off
setlocal
cd /d "%~dp0"
title Lector de cheques

if not exist "glm_ocr_merged\config.json" (
  echo.
  echo No encuentro el modelo. Copia la carpeta "glm_ocr_merged" junto a este archivo
  echo y vuelve a ejecutarlo. Debe contener model.safetensors y config.json.
  echo Si el archivo se llama model-001.safetensors, renombralo a model.safetensors.
  echo.
  pause
  exit /b 1
)

if not exist "reglas.json" (
  echo.
  echo No encuentro reglas.json junto a este archivo.
  echo Sin ese archivo no se puede validar la fecha ni generar el informe.
  echo.
  pause
  exit /b 1
)

if not exist "entrada" mkdir "entrada"
if not exist "informes" mkdir "informes"

if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno de Python ^(solo la primera vez^)...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo.
    echo No encuentro Python. Instala Python 3.10 o superior desde https://www.python.org
    echo y marca la casilla "Add Python to PATH" durante la instalacion.
    echo.
    pause
    exit /b 1
  )
)

rem Comprueba de verdad que las librerias esten instaladas; si falta alguna, las instala.
".venv\Scripts\python.exe" -c "import flask, PIL, torch, torchvision, accelerate, transformers, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo Instalando o reparando dependencias ^(puede tardar varios minutos^)...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Fallo la instalacion. Revisa tu conexion a internet y vuelve a intentarlo.
    echo Si el error continua, ejecuta reparar.bat.
    echo.
    pause
    exit /b 1
  )
  echo.
  echo Comprobando la instalacion...
  ".venv\Scripts\python.exe" -c "import flask, PIL, torch, torchvision, accelerate, transformers, openpyxl"
  if errorlevel 1 (
    echo.
    echo Las librerias siguen sin cargar. Ejecuta reparar.bat.
    echo Si vuelve a fallar, copia el error y envialo para revisarlo.
    echo.
    pause
    exit /b 1
  )
)

echo.
echo Como usarlo:
echo   1. Copia las imagenes de los cheques en la carpeta "entrada".
echo   2. En el navegador pulsa "Leer carpeta y generar informe".
echo   3. El Excel queda en la carpeta "informes".
echo      Solo incluye los cheques con observaciones.
echo.
echo Las reglas de fecha y de validacion estan en reglas.json.
echo La guia completa esta en README.md.
echo.
echo Cargando el modelo. Se abrira el navegador cuando este listo...
echo Para cerrar el programa, cierra esta ventana.
echo.
".venv\Scripts\python.exe" app.py
echo.
echo El programa se cerro.
pause
