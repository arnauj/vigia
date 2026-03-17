# ============================================================================
# VIGIA Client - Instalador PowerShell para Windows
# Uso: powershell -ExecutionPolicy Bypass -File instalar_cliente.ps1 [IP_SERVIDOR]
# ============================================================================

param(
    [string]$ServerIP = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  VIGIA Client - Instalador Windows" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# -- Verificar Python --
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $python = $cmd
            Write-Host "[OK] Python encontrado: $ver" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $python) {
    Write-Host "[ERROR] Python 3 no encontrado. Descargalo de https://python.org" -ForegroundColor Red
    exit 1
}

# -- Pedir IP del servidor si no se proporcionó --
if (-not $ServerIP) {
    try {
        $localIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notlike "*Loopback*" -and $_.PrefixOrigin -eq "Dhcp" } | Select-Object -First 1).IPAddress
        if ($localIP) {
            $parts = $localIP.Split(".")
            $parts[3] = "2"
            $defaultIP = $parts -join "."
        } else {
            $defaultIP = "192.168.1.2"
        }
    } catch {
        $defaultIP = "192.168.1.2"
    }
    $ServerIP = Read-Host "IP del servidor VIGIA [$defaultIP]"
    if (-not $ServerIP) { $ServerIP = $defaultIP }
}

Write-Host "[*] Servidor: $ServerIP" -ForegroundColor Cyan

# -- Crear venv --
$VenvDir = Join-Path $ScriptDir "venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "[*] Creando entorno virtual..."
    & $python -m venv $VenvDir
}

$PipExe = Join-Path $VenvDir "Scripts\pip.exe"
$PythonwExe = Join-Path $VenvDir "Scripts\pythonw.exe"

# -- Instalar dependencias --
Write-Host "[*] Instalando dependencias del cliente..."
& $PipExe install python-socketio[client] websocket-client mss Pillow pynput

# -- Guardar IP en configuración --
$ConfigDir = Join-Path $env:APPDATA "vigia"
if (-not (Test-Path $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
}
$ConfigFile = Join-Path $ConfigDir "client.conf"
Set-Content -Path $ConfigFile -Value $ServerIP -NoNewline
Write-Host "[OK] IP guardada en $ConfigFile" -ForegroundColor Green

# -- Crear .vbs silencioso para lanzar sin consola --
$ClientPy = Join-Path $ScriptDir "client.py"
$ClientVbs = Join-Path $ScriptDir "run-client.vbs"
Set-Content -Path $ClientVbs -Value @"
CreateObject("WScript.Shell").Run """$PythonwExe"" ""$ClientPy"" $ServerIP", 0, False
"@
Write-Host "[OK] Script de lanzamiento silencioso creado" -ForegroundColor Green

# -- Crear acceso directo en Startup (auto-arranque via wscript, CERO consola) --
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "VIGIA Client.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "`"$ClientVbs`""
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.Description = "VIGIA - Cliente del Alumno"
$IconPath = Join-Path $ScriptDir "img\logo2.ico"
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
}
$Shortcut.Save()
Write-Host "[OK] Auto-arranque configurado (Startup, sin consola)" -ForegroundColor Green

# -- Crear acceso directo en Start Menu --
$StartMenu = [Environment]::GetFolderPath("CommonStartMenu")
$MenuShortcut = Join-Path $StartMenu "Programs\VIGIA Client.lnk"
$Shortcut2 = $WshShell.CreateShortcut($MenuShortcut)
$Shortcut2.TargetPath = "wscript.exe"
$Shortcut2.Arguments = "`"$ClientVbs`""
$Shortcut2.WorkingDirectory = $ScriptDir
$Shortcut2.Description = "VIGIA - Cliente del Alumno"
if (Test-Path $IconPath) {
    $Shortcut2.IconLocation = $IconPath
}
$Shortcut2.Save()
Write-Host "[OK] Acceso directo creado en Start Menu" -ForegroundColor Green

# -- Arrancar el cliente inmediatamente (sin consola) --
Write-Host "[*] Arrancando cliente en segundo plano..."
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$ClientVbs`"" -WindowStyle Hidden

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Instalacion completada!" -ForegroundColor Green
Write-Host "  Cliente conectando a: $ServerIP (sin consola)" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
