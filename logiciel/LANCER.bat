@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python n'est pas installe ou pas dans le PATH.
    echo Telechargez-le sur https://www.python.org/downloads/
    echo puis relancez ce fichier.
    pause
    exit /b 1
)

python retrio.py
if errorlevel 1 (
    echo.
    echo Une erreur s'est produite. Fermez cette fenetre pour l'analyser.
    pause
)
