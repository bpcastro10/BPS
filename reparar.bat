@echo off
setlocal
cd /d "%~dp0"
title Reparar dependencias del lector de cheques

echo Este archivo vuelve a instalar las librerias del lector.
echo Usalo cuando iniciar.bat diga que falta una libreria o que la instalacion fallo.
echo No lee cheques ni genera el informe. Despues de reparar, ejecuta iniciar.bat.
echo.

if not exist ".venv\Scripts\python.exe" (
  echo No existe la carpeta .venv. Ejecuta primero iniciar.bat para crearla.
  echo.
  pause
  exit /b 1
)

echo Version de Python del entorno:
".venv\Scripts\python.exe" --version
echo.
echo Instalando torch y torchvision ^(puede tardar varios minutos^)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fallo
".venv\Scripts\python.exe" -m pip install --upgrade torch torchvision
if errorlevel 1 goto fallo
echo.
echo Instalando el resto de librerias, incluido openpyxl para el Excel...
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
if errorlevel 1 goto fallo
echo.
echo ===== Resultado =====
".venv\Scripts\python.exe" -m pip show torchvision
echo.
".venv\Scripts\python.exe" -c "import flask, PIL, torch, torchvision, accelerate, transformers, openpyxl; print('Todo instalado correctamente')"
if errorlevel 1 goto fallo
echo.
echo Listo. Ahora ejecuta iniciar.bat.
echo.
pause
exit /b 0

:fallo
echo.
echo La reparacion no termino. Revisa el mensaje de arriba y tu conexion a internet.
echo.
pause
exit /b 1
