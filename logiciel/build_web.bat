@echo off
cd /d "%~dp0"
echo Installation des dependances (pywebview + pythonnet)...
python -m pip install --disable-pip-version-check --quiet pywebview pythonnet
if errorlevel 1 (
    echo ERREUR lors de l'installation des dependances.
    pause
    exit /b 1
)
echo.
echo Nettoyage des builds precedents (spec/onedir en cache)...
if exist "RetrioWeb.spec" del /q "RetrioWeb.spec"
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
echo.
echo Compilation de RetrioWeb.exe (dossier, demarrage rapide)...
python -m PyInstaller --noconfirm --onedir --windowed --name "RetrioWeb" --icon "icon.ico" ^
  --add-data "app.html;." --add-data "app.css;." --add-data "app.js;." --add-data "fonts;fonts" ^
  --add-data "icon.ico;." ^
  retrio_web.py
echo.
echo Termine. Le fichier se trouve dans dist\RetrioWeb\RetrioWeb.exe
pause
