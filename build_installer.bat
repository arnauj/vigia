@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ────────────────────────────────────────────────────────────────
::  VIGIA — Constructor de instaladores Windows
::  Genera un directorio dist_win/ con todo lo necesario para
::  distribuir VIGIA en Windows (servidor y cliente).
::
::  Equivalente de build_debs.sh para Windows.
::  En lugar de .deb genera un directorio autocontenido +
::  script Inno Setup (.iss) si Inno Setup está instalado.
:: ────────────────────────────────────────────────────────────────

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "VERSION=1.1"
set "DIST_DIR=%SCRIPT_DIR%\dist_win"

echo.
echo ═══════════════════════════════════════════════
echo   VIGIA v%VERSION% — Construyendo instaladores Windows
echo ═══════════════════════════════════════════════
echo.

:: Limpiar distribución anterior
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
mkdir "%DIST_DIR%"

:: ── BUILD SERVER PACKAGE ──────────────────────────────────────
echo [*] Construyendo paquete del servidor...
set "SERVER_DIR=%DIST_DIR%\vigia-server"
mkdir "%SERVER_DIR%"
mkdir "%SERVER_DIR%\templates"
mkdir "%SERVER_DIR%\img"

copy "%SCRIPT_DIR%\server.py" "%SERVER_DIR%\" >nul
copy "%SCRIPT_DIR%\vigia-launcher-win.py" "%SERVER_DIR%\" >nul
copy "%SCRIPT_DIR%\templates\*" "%SERVER_DIR%\templates\" >nul
copy "%SCRIPT_DIR%\img\logo2.png" "%SERVER_DIR%\img\" >nul 2>nul
copy "%SCRIPT_DIR%\img\logo2_mini.png" "%SERVER_DIR%\img\" >nul 2>nul
if exist "%SCRIPT_DIR%\img\icon-192.png" copy "%SCRIPT_DIR%\img\icon-192.png" "%SERVER_DIR%\img\" >nul
if exist "%SCRIPT_DIR%\img\icon-512.png" copy "%SCRIPT_DIR%\img\icon-512.png" "%SERVER_DIR%\img\" >nul
copy "%SCRIPT_DIR%\instalar_servidor_win.bat" "%SERVER_DIR%\" >nul

:: Crear script de instalación rápida
(
    echo @echo off
    echo cd /d "%%~dp0"
    echo call instalar_servidor_win.bat
) > "%SERVER_DIR%\INSTALAR.bat"

:: Crear script de desinstalación
(
    echo @echo off
    echo echo Desinstalando VIGIA Servidor...
    echo reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "VIGIA-Servidor" /f 2^>nul
    echo del "%%USERPROFILE%%\Desktop\VIGIA Servidor.lnk" 2^>nul
    echo del "%%APPDATA%%\Microsoft\Windows\Start Menu\Programs\VIGIA Servidor.lnk" 2^>nul
    echo netsh advfirewall firewall delete rule name="VIGIA Servidor" 2^>nul
    echo echo [OK] VIGIA Servidor desinstalado.
    echo pause
) > "%SERVER_DIR%\DESINSTALAR.bat"

echo [OK] Paquete del servidor creado en %SERVER_DIR%

:: ── BUILD CLIENT PACKAGE ──────────────────────────────────────
echo [*] Construyendo paquete del cliente...
set "CLIENT_DIR=%DIST_DIR%\vigia-client"
mkdir "%CLIENT_DIR%"
mkdir "%CLIENT_DIR%\img"

copy "%SCRIPT_DIR%\client_win.py" "%CLIENT_DIR%\" >nul
copy "%SCRIPT_DIR%\vigia_overlay_win.py" "%CLIENT_DIR%\" >nul
copy "%SCRIPT_DIR%\img\logo2_mini.png" "%CLIENT_DIR%\img\" >nul 2>nul
copy "%SCRIPT_DIR%\instalar_cliente_win.bat" "%CLIENT_DIR%\" >nul

:: Crear script de instalación rápida
(
    echo @echo off
    echo cd /d "%%~dp0"
    echo set /p IP="IP del servidor [192.168.1.2]: "
    echo if "%%IP%%"=="" set "IP=192.168.1.2"
    echo call instalar_cliente_win.bat %%IP%%
) > "%CLIENT_DIR%\INSTALAR.bat"

:: Crear script de desinstalación
(
    echo @echo off
    echo echo Desinstalando VIGIA Cliente...
    echo taskkill /f /fi "WINDOWTITLE eq VIGIA*" 2^>nul
    echo reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "VIGIA-Cliente" /f 2^>nul
    echo del "%%USERPROFILE%%\Desktop\VIGIA Alumno.lnk" 2^>nul
    echo del "%%APPDATA%%\Microsoft\Windows\Start Menu\Programs\VIGIA Alumno.lnk" 2^>nul
    echo del "%%APPDATA%%\Microsoft\Windows\Start Menu\Programs\Startup\VIGIA Alumno.lnk" 2^>nul
    echo netsh advfirewall firewall delete rule name="VIGIA Cliente" 2^>nul
    echo echo [OK] VIGIA Cliente desinstalado.
    echo pause
) > "%CLIENT_DIR%\DESINSTALAR.bat"

echo [OK] Paquete del cliente creado en %CLIENT_DIR%

:: ── GENERAR SCRIPT INNO SETUP (servidor) ──────────────────────
echo [*] Generando script Inno Setup...

set "ISS_SERVER=%DIST_DIR%\vigia-server-setup.iss"
(
    echo [Setup]
    echo AppName=VIGIA Servidor
    echo AppVersion=%VERSION%
    echo AppPublisher=VIGIA
    echo DefaultDirName={autopf}\VIGIA-Server
    echo DefaultGroupName=VIGIA
    echo OutputDir=%DIST_DIR%
    echo OutputBaseFilename=vigia-server-setup_%VERSION%
    echo Compression=lzma
    echo SolidCompression=yes
    echo PrivilegesRequired=admin
    echo.
    echo [Files]
    echo Source: "%SERVER_DIR%\*"; DestDir: "{app}"; Flags: recursesubdirs
    echo.
    echo [Icons]
    echo Name: "{group}\VIGIA Servidor"; Filename: "{cmd}"; Parameters: "/c python ""{app}\vigia-launcher-win.py"""; WorkingDir: "{app}"; IconFilename: "{app}\img\logo2_mini.png"
    echo Name: "{commondesktop}\VIGIA Servidor"; Filename: "{cmd}"; Parameters: "/c python ""{app}\vigia-launcher-win.py"""; WorkingDir: "{app}"; IconFilename: "{app}\img\logo2_mini.png"
    echo.
    echo [Run]
    echo Filename: "{cmd}"; Parameters: "/c ""{app}\instalar_servidor_win.bat"""; StatusMsg: "Configurando VIGIA Servidor..."; Flags: runhidden
    echo.
    echo [UninstallRun]
    echo Filename: "{cmd}"; Parameters: "/c ""{app}\DESINSTALAR.bat"""; Flags: runhidden
) > "%ISS_SERVER%"

set "ISS_CLIENT=%DIST_DIR%\vigia-client-setup.iss"
(
    echo [Setup]
    echo AppName=VIGIA Cliente
    echo AppVersion=%VERSION%
    echo AppPublisher=VIGIA
    echo DefaultDirName={autopf}\VIGIA-Client
    echo DefaultGroupName=VIGIA
    echo OutputDir=%DIST_DIR%
    echo OutputBaseFilename=vigia-client-setup_%VERSION%
    echo Compression=lzma
    echo SolidCompression=yes
    echo PrivilegesRequired=admin
    echo.
    echo [Files]
    echo Source: "%CLIENT_DIR%\*"; DestDir: "{app}"; Flags: recursesubdirs
    echo.
    echo [Icons]
    echo Name: "{group}\VIGIA Alumno"; Filename: "{cmd}"; Parameters: "/c python ""{app}\client_win.py"""; WorkingDir: "{app}"; IconFilename: "{app}\img\logo2_mini.png"
    echo.
    echo [Run]
    echo Filename: "{cmd}"; Parameters: "/c ""{app}\instalar_cliente_win.bat"""; StatusMsg: "Configurando VIGIA Cliente..."; Flags: runhidden
    echo.
    echo [UninstallRun]
    echo Filename: "{cmd}"; Parameters: "/c ""{app}\DESINSTALAR.bat"""; Flags: runhidden
) > "%ISS_CLIENT%"

echo [OK] Scripts Inno Setup generados

:: ── COMPILAR CON INNO SETUP (si está disponible) ──────────────
set "ISCC="
for %%p in (
    "%PROGRAMFILES(x86)%\Inno Setup 6\ISCC.exe"
    "%PROGRAMFILES%\Inno Setup 6\ISCC.exe"
    "%PROGRAMFILES(x86)%\Inno Setup 5\ISCC.exe"
) do (
    if exist %%p (
        set "ISCC=%%~p"
        goto :iscc_found
    )
)

echo [!] Inno Setup no encontrado. Los .iss están listos para compilar manualmente.
echo     Descarga Inno Setup de: https://jrsoftware.org/isdl.php
goto :skip_compile

:iscc_found
echo [*] Compilando instaladores con Inno Setup...
"%ISCC%" "%ISS_SERVER%" >nul 2>&1
if not errorlevel 1 (
    echo [OK] vigia-server-setup_%VERSION%.exe generado
) else (
    echo [!] Error compilando instalador del servidor
)

"%ISCC%" "%ISS_CLIENT%" >nul 2>&1
if not errorlevel 1 (
    echo [OK] vigia-client-setup_%VERSION%.exe generado
) else (
    echo [!] Error compilando instalador del cliente
)

:skip_compile

echo.
echo ═══════════════════════════════════════════════
echo   [OK] Build completado.
echo   Paquetes en: %DIST_DIR%
echo ═══════════════════════════════════════════════
echo.
echo   Contenido:
echo     vigia-server\       Directorio servidor (copiar + ejecutar INSTALAR.bat)
echo     vigia-client\       Directorio cliente  (copiar + ejecutar INSTALAR.bat)
echo     *.iss               Scripts Inno Setup (compilar con ISCC)
if exist "%DIST_DIR%\vigia-server-setup_%VERSION%.exe" echo     vigia-server-setup_%VERSION%.exe
if exist "%DIST_DIR%\vigia-client-setup_%VERSION%.exe" echo     vigia-client-setup_%VERSION%.exe
echo.
pause
