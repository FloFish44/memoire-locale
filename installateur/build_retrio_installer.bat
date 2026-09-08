@echo off
cd /d "%~dp0"
echo Compilation de Installateur_Retrio.exe...
python -m PyInstaller --noconfirm --onefile --windowed --name "Installateur_Retrio" --icon "retrio_icon.ico" --add-data "retrio_icon.ico;." retrio_installer.py
echo.
echo Termine. Le fichier se trouve dans dist\Installateur_Retrio.exe
pause
