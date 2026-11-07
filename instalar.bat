@echo off
REM Instalación de PixAgent en Windows (requiere Python 3.10+ en el PATH)
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e .
echo.
echo Listo. Configura tu clave:  setx ANTHROPIC_API_KEY "tu_clave"
echo Luego ejecuta iniciar.bat
pause
