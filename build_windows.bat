@echo off
REM ============================================================================
REM VIGIA - Script de empaquetado Windows
REM Genera vigia-servidor.exe, vigia-launcher.exe y vigia-cliente.exe
REM Todos sin ventana de consola (--noconsole / --windowed)
REM Requisitos: Python 3.10+, pip, PyInstaller
REM ============================================================================

setlocal enabledelayedexpansion

echo [VIGIA] Generando ejecutables Windows...
echo.

REM -- Verificar Python --
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.10+ y agrégalo al PATH.
    exit /b 1
)

REM -- Verificar/instalar PyInstaller --
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [*] Instalando PyInstaller...
    pip install pyinstaller
)

REM -- Verificar/instalar dependencias --
echo [*] Instalando dependencias...
pip install -r requirements_windows.txt

REM -- Crear directorio de salida --
if not exist dist\windows mkdir dist\windows

REM -- Generar icono .ico si no existe --
if not exist img\logo2.ico (
    echo [*] Generando logo2.ico desde logo2.png...
    python -c "from PIL import Image; img = Image.open('img/logo2.png'); img.save('img/logo2.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])" 2>nul
    if errorlevel 1 (
        echo [!] No se pudo generar .ico; continuando sin icono personalizado.
    )
)

REM -- Determinar parametro de icono --
set "ICON_PARAM="
if exist img\logo2.ico set "ICON_PARAM=--icon=img\logo2.ico"

REM -- Servidor (sin consola, ejecuta en segundo plano) --
echo.
echo [VIGIA] Empaquetando servidor...
python -m PyInstaller ^
    --noconfirm ^
    --noconsole ^
    --onedir ^
    --name vigia-servidor ^
    %ICON_PARAM% ^
    --add-data "templates;templates" ^
    --add-data "img;img" ^
    --add-data "platform_utils.py;." ^
    --collect-all eventlet ^
    --collect-all dns ^
    --collect-all engineio ^
    --collect-all socketio ^
    --collect-all flask_socketio ^
    --distpath dist\windows ^
    server.py

if errorlevel 1 (
    echo [ERROR] Fallo al empaquetar el servidor.
    exit /b 1
)

REM -- Launcher (sin consola, abre el dashboard en Chrome) --
echo.
echo [VIGIA] Empaquetando launcher...
python -m PyInstaller ^
    --noconfirm ^
    --noconsole ^
    --onedir ^
    --name vigia-launcher ^
    %ICON_PARAM% ^
    --add-data "img;img" ^
    --add-data "platform_utils.py;." ^
    --distpath dist\windows ^
    vigia-launcher.py

if errorlevel 1 (
    echo [ERROR] Fallo al empaquetar el launcher.
    exit /b 1
)

REM -- Copiar archivos auxiliares al servidor y launcher --
copy /y platform_utils.py dist\windows\vigia-servidor\ >nul
copy /y platform_utils.py dist\windows\vigia-launcher\ >nul
REM -- Copiar wrapper VBS del servidor (antes de empaquetar cliente que no toca esta carpeta) --
copy /y vigia-servidor-silent.vbs dist\windows\vigia-servidor\ >nul

REM -- Cliente (sin consola, ejecuta en segundo plano) --
echo.
echo [VIGIA] Empaquetando cliente...
python -m PyInstaller ^
    --noconfirm ^
    --noconsole ^
    --onedir ^
    --name vigia-cliente ^
    %ICON_PARAM% ^
    --add-data "img;img" ^
    --add-data "platform_utils.py;." ^
    --collect-all pynput ^
    --distpath dist\windows ^
    client.py

if errorlevel 1 (
    echo [ERROR] Fallo al empaquetar el cliente.
    exit /b 1
)

copy /y platform_utils.py dist\windows\vigia-cliente\ >nul
REM -- Copiar wrapper VBS del cliente (DESPUES de PyInstaller para que no lo borre) --
copy /y vigia-cliente-silent.vbs dist\windows\vigia-cliente\ >nul

echo.
echo ============================================================================
echo [OK] Ejecutables generados en dist\windows\
echo   - dist\windows\vigia-servidor\vigia-servidor.exe  (servidor, segundo plano)
echo   - dist\windows\vigia-launcher\vigia-launcher.exe  (abre dashboard + servidor)
echo   - dist\windows\vigia-cliente\vigia-cliente.exe    (cliente, segundo plano)
echo ============================================================================
echo.
echo Para generar instaladores, usa Inno Setup con:
echo   iscc vigia-server.iss
echo   iscc vigia-client.iss

endlocal
