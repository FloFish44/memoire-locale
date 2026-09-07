@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python n'est pas installe ou pas dans le PATH.
    echo Telechargez-le sur https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installation de PyInstaller (si necessaire)...
python -m pip install --upgrade pyinstaller >nul

echo Compilation de l'executable...
python -m PyInstaller --noconfirm --onefile --windowed --name "Memoire_locale" memoire_locale.py

echo.
echo Termine. Executable disponible dans dist\Memoire_locale.exe
pause
