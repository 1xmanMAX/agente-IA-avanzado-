@echo off
REM Abre la interfaz de PixAgent en el navegador
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m pixagent serve %*
