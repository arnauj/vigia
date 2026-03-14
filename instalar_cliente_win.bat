@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

set "IP_SERVIDOR=%~1"
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: ── Si no se pasa IP, calcular X.X.X.2 ─────────────────────
if "%IP_SERVIDOR%"=="" (
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4"') do (
        for /f "tokens=1-4 delims=." %%i in ("%%a") do (
            set "IP_SERVIDOR=%%i.%%j.%%k.2"
            set "IP_SERVIDOR=!IP_SERVIDOR: =!"
            goto :ip_found
        )
    )
)
:ip_found

echo.
echo ═══════════════════════════════════════════════
echo   VIGIA v1.3 — Instalando cliente del alumno (Windows)
echo ═══════════════════════════════════════════════
echo.

:: ── Detectar Python 3 ─────────────────────────────────────────
set "PYTHON3="
for %%p in (python py python3) do (
    where %%p >nul 2>&1
    if not errorlevel 1 (
        for /f "tokens=*" %%v in ('%%p --version 2^>^&1') do (
            echo %%v | findstr /C:"Python 3" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON3=%%p"
                goto :python_found
            )
        )
    )
)

echo [!] Python 3 no encontrado. Descárgalo de:
echo     https://www.python.org/downloads/
echo     Marca "Add Python to PATH" durante la instalación.
pause
exit /b 1

:python_found
echo [OK] Python: %PYTHON3%

:: ── Verificar/instalar pip ───────────────────────────────────
echo [*] Verificando pip...
%PYTHON3% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [*] Instalando pip...
    %PYTHON3% -m ensurepip --default-pip 2>nul
)
echo [OK] pip disponible

:: ── Instalar dependencias Python ──────────────────────────────
echo [*] Instalando dependencias Python...
%PYTHON3% -m pip install --user -q "python-socketio[client]" websocket-client mss Pillow pynput 2>nul

:: ── Guardar IP del servidor ──────────────────────────────────
set "CONFIG_DIR=%PROGRAMDATA%\vigia"
if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"
echo %IP_SERVIDOR%> "%CONFIG_DIR%\client.conf"
echo [OK] IP del servidor: %IP_SERVIDOR%

:: ── Crear acceso directo en el escritorio ─────────────────────
echo [*] Creando accesos directos...
set "DESKTOP=%USERPROFILE%\Desktop"
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"

set "VBS_FILE=%TEMP%\vigia_client_shortcut.vbs"
(
    echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
    echo Set oLink = oWS.CreateShortcut^("%DESKTOP%\VIGIA Alumno.lnk"^)
    echo oLink.TargetPath = "%PYTHON3%"
    echo oLink.Arguments = """%SCRIPT_DIR%\client_win.py"" %IP_SERVIDOR%"
    echo oLink.WorkingDirectory = "%SCRIPT_DIR%"
    echo oLink.Description = "VIGIA - Cliente del alumno"
    echo oLink.IconLocation = "%SCRIPT_DIR%\img\logo2_mini.png"
    echo oLink.WindowStyle = 7
    echo oLink.Save
) > "%VBS_FILE%"
cscript //nologo "%VBS_FILE%" 2>nul
del "%VBS_FILE%" 2>nul

:: Menú inicio
set "VBS_FILE=%TEMP%\vigia_client_startmenu.vbs"
(
    echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
    echo Set oLink = oWS.CreateShortcut^("%STARTMENU%\VIGIA Alumno.lnk"^)
    echo oLink.TargetPath = "%PYTHON3%"
    echo oLink.Arguments = """%SCRIPT_DIR%\client_win.py"" %IP_SERVIDOR%"
    echo oLink.WorkingDirectory = "%SCRIPT_DIR%"
    echo oLink.Description = "VIGIA - Cliente del alumno"
    echo oLink.IconLocation = "%SCRIPT_DIR%\img\logo2_mini.png"
    echo oLink.WindowStyle = 7
    echo oLink.Save
) > "%VBS_FILE%"
cscript //nologo "%VBS_FILE%" 2>nul
del "%VBS_FILE%" 2>nul

echo [OK] Accesos directos creados

:: ── Configurar inicio automático ──────────────────────────────
echo [*] Configurando inicio automático del cliente...

:: Crear wrapper script
set "WRAPPER=%SCRIPT_DIR%\vigia-client-service.bat"
(
    echo @echo off
    echo cd /d "%SCRIPT_DIR%"
    echo "%PYTHON3%" "%SCRIPT_DIR%\client_win.py" %IP_SERVIDOR%
) > "%WRAPPER%"

:: Agregar al inicio automático de Windows via registro
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "VIGIA-Cliente" /t REG_SZ /d "\"%WRAPPER%\"" /f >nul 2>&1

:: También copiar a la carpeta de Startup como respaldo
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS_FILE=%TEMP%\vigia_client_startup.vbs"
(
    echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
    echo Set oLink = oWS.CreateShortcut^("%STARTUP%\VIGIA Alumno.lnk"^)
    echo oLink.TargetPath = "%PYTHON3%"
    echo oLink.Arguments = """%SCRIPT_DIR%\client_win.py"" %IP_SERVIDOR%"
    echo oLink.WorkingDirectory = "%SCRIPT_DIR%"
    echo oLink.Description = "VIGIA - Cliente del alumno (inicio automático)"
    echo oLink.WindowStyle = 7
    echo oLink.Save
) > "%VBS_FILE%"
cscript //nologo "%VBS_FILE%" 2>nul
del "%VBS_FILE%" 2>nul

echo [OK] Inicio automático configurado.
echo     El cliente arrancará automáticamente al iniciar sesión.

:: ── Regla de firewall (si se ejecuta como admin) ─────────────
netsh advfirewall firewall show rule name="VIGIA Cliente" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="VIGIA Cliente" dir=out action=allow protocol=TCP remoteport=5000 >nul 2>&1
)

:: ── Matar instancia previa y arrancar cliente ─────────────────
echo [*] Iniciando cliente VIGIA...
taskkill /f /im python.exe /fi "WINDOWTITLE eq VIGIA*" >nul 2>&1
start "" /b %PYTHON3% "%SCRIPT_DIR%\client_win.py" %IP_SERVIDOR%

echo.
echo ═══════════════════════════════════════════════
echo   [OK] Instalación completada.
echo   Servidor: %IP_SERVIDOR%
echo ═══════════════════════════════════════════════
echo.
pause
