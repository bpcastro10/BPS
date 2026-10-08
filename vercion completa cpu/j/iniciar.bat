@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
echo Instalando dependencias (solo la primera vez tarda)...
python -m pip install -q -r requirements.txt
echo.
echo Abriendo http://127.0.0.1:8000  (Ctrl+C para detener)
start "" http://127.0.0.1:8000
python run.py
