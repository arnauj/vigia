@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo.
echo ═══════════════════════════════════════════════
echo   VIGIA v1.1 — Instalando servidor del profesor (Windows)
echo ═══════════════════════════════════════════════
echo.

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

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

:python_not_found
echo [!] Python 3 no encontrado. Descárgalo de:
echo     https://www.python.org/downloads/
echo.
echo     Asegúrate de marcar "Add Python to PATH" durante la instalación.
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
    %PYTHON3% -m pip --version >nul 2>&1
    if errorlevel 1 (
        echo [!] No se pudo instalar pip.
        echo     Ejecuta: %PYTHON3% -m ensurepip --default-pip
        pause
        exit /b 1
    )
)
echo [OK] pip disponible

:: ── Instalar dependencias Python ──────────────────────────────
echo [*] Instalando dependencias Python...
%PYTHON3% -m pip install --user -q flask flask-socketio eventlet mss Pillow 2>nul
if errorlevel 1 (
    echo [!] Advertencia: algunas dependencias pueden no haberse instalado correctamente.
)

:: ── Crear acceso directo en el escritorio ─────────────────────
echo [*] Creando acceso directo en el escritorio...
set "DESKTOP=%USERPROFILE%\Desktop"
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"

:: Crear script VBS para generar acceso directo
set "VBS_FILE=%TEMP%\vigia_shortcut.vbs"
(
    echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
    echo Set oLink = oWS.CreateShortcut^("%DESKTOP%\VIGIA Servidor.lnk"^)
    echo oLink.TargetPath = "%PYTHON3%"
    echo oLink.Arguments = """%SCRIPT_DIR%\vigia-launcher-win.py"""
    echo oLink.WorkingDirectory = "%SCRIPT_DIR%"
    echo oLink.Description = "VIGIA - Panel del profesor"
    echo oLink.IconLocation = "%SCRIPT_DIR%\img\logo2_mini.png"
    echo oLink.Save
) > "%VBS_FILE%"
cscript //nologo "%VBS_FILE%" 2>nul
del "%VBS_FILE%" 2>nul

:: Crear también en menú inicio
set "VBS_FILE=%TEMP%\vigia_startmenu.vbs"
(
    echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
    echo Set oLink = oWS.CreateShortcut^("%STARTMENU%\VIGIA Servidor.lnk"^)
    echo oLink.TargetPath = "%PYTHON3%"
    echo oLink.Arguments = """%SCRIPT_DIR%\vigia-launcher-win.py"""
    echo oLink.WorkingDirectory = "%SCRIPT_DIR%"
    echo oLink.Description = "VIGIA - Panel del profesor"
    echo oLink.IconLocation = "%SCRIPT_DIR%\img\logo2_mini.png"
    echo oLink.Save
) > "%VBS_FILE%"
cscript //nologo "%VBS_FILE%" 2>nul
del "%VBS_FILE%" 2>nul

echo [OK] Accesos directos creados

:: ── Configurar inicio automático (Registro de Windows) ────────
echo [*] Configurando inicio automático del servidor...

:: Crear un script .bat wrapper para el servicio
set "WRAPPER=%SCRIPT_DIR%\vigia-server-service.bat"
(
    echo @echo off
    echo cd /d "%SCRIPT_DIR%"
    echo "%PYTHON3%" "%SCRIPT_DIR%\server.py" 5000
) > "%WRAPPER%"

:: Agregar al registro de Windows para auto-inicio
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "VIGIA-Servidor" /t REG_SZ /d "\"%WRAPPER%\"" /f >nul 2>&1

echo [OK] Servidor configurado para inicio automático.
echo     Para desactivar: Panel de control ^> Aplicaciones de inicio

:: ── Regla de firewall ─────────────────────────────────────────
echo [*] Configurando regla de firewall...
:: Intentar agregar regla de firewall (requiere Admin)
netsh advfirewall firewall show rule name="VIGIA Servidor" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="VIGIA Servidor" dir=in action=allow protocol=TCP localport=5000 >nul 2>&1
    if errorlevel 1 (
        echo [!] No se pudo agregar regla de firewall (se necesitan permisos de administrador).
        echo     Ejecuta este script como administrador o agrega la regla manualmente:
        echo     Permitir conexiones entrantes TCP en el puerto 5000
    ) else (
        echo [OK] Regla de firewall creada para puerto 5000
    )
) else (
    echo [OK] Regla de firewall ya existe
)

:: ── Iniciar servidor ahora ────────────────────────────────────
echo [*] Iniciando servidor VIGIA...
start "" /b %PYTHON3% "%SCRIPT_DIR%\server.py" 5000

echo.
echo ═══════════════════════════════════════════════
echo   [OK] Instalación completada con éxito.
echo ═══════════════════════════════════════════════
echo.
echo   Comandos útiles:
echo     Iniciar servidor: python vigia-launcher-win.py
echo     Iniciar solo Flask: python server.py
echo.
pause
