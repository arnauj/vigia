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
    # Intentar auto-detectar: IP local con ultimo octeto = .2
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
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

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

# -- Crear acceso directo en Startup (auto-arranque) --
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "VIGIA Client.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PythonExe
$Shortcut.Arguments = "`"$(Join-Path $ScriptDir 'client.py')`" $ServerIP"
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.Description = "VIGIA - Cliente del Alumno"
$Shortcut.WindowStyle = 7  # Minimized
$IconPath = Join-Path $ScriptDir "img\logo2.ico"
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
}
$Shortcut.Save()
Write-Host "[OK] Auto-arranque configurado (Startup)" -ForegroundColor Green

# -- Crear acceso directo en Start Menu --
$StartMenu = [Environment]::GetFolderPath("CommonStartMenu")
$MenuShortcut = Join-Path $StartMenu "Programs\VIGIA Client.lnk"
$Shortcut2 = $WshShell.CreateShortcut($MenuShortcut)
$Shortcut2.TargetPath = $PythonExe
$Shortcut2.Arguments = "`"$(Join-Path $ScriptDir 'client.py')`" $ServerIP"
$Shortcut2.WorkingDirectory = $ScriptDir
$Shortcut2.Description = "VIGIA - Cliente del Alumno"
if (Test-Path $IconPath) {
    $Shortcut2.IconLocation = $IconPath
}
$Shortcut2.Save()
Write-Host "[OK] Acceso directo creado en Start Menu" -ForegroundColor Green

# -- Arrancar el cliente inmediatamente --
Write-Host "[*] Arrancando cliente..."
Start-Process -FilePath $PythonExe -ArgumentList "`"$(Join-Path $ScriptDir 'client.py')`" $ServerIP" -WorkingDirectory $ScriptDir -WindowStyle Minimized

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Instalacion completada!" -ForegroundColor Green
Write-Host "  Cliente conectando a: $ServerIP" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
