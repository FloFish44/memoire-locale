@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller==6.22.2
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --onedir --windowed --name "RetrioWeb" --icon "icon.ico" ^
  --add-data "app.html;." --add-data "app.css;." --add-data "app.js;." --add-data "demo-retrio.mp4;." --add-data "fonts;fonts" ^
  --add-data "icon.ico;." --add-data "models;models" --collect-all onnxruntime --collect-all pypdfium2 --collect-all pypdfium2_raw ^
  --collect-all winrt --hidden-import winrt.windows.foundation.collections ^
  retrio_web.py
if errorlevel 1 exit /b 1
echo Retrio 0.5.0 disponible dans dist\RetrioWeb\RetrioWeb.exe
pause
