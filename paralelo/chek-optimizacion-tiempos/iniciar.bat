@echo off
rem Levanta la interfaz de prueba en http://127.0.0.1:8300 (solo este equipo)
cd /d "%~dp0"
rem Pregunta CPU/GPU y procesos; abre el navegador cuando los modelos esten listos
.venv\Scripts\python servidor.py --abrir-navegador
pause
