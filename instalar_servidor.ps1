# ============================================================================
# VIGIA Server - Instalador PowerShell para Windows
# Uso: powershell -ExecutionPolicy Bypass -File instalar_servidor.ps1
# ============================================================================

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  VIGIA Server - Instalador Windows" -ForegroundColor Cyan
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

# -- Crear venv --
$VenvDir = Join-Path $ScriptDir "venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "[*] Creando entorno virtual..."
    & $python -m venv $VenvDir
}

$PipExe = Join-Path $VenvDir "Scripts\pip.exe"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

# -- Instalar dependencias --
Write-Host "[*] Instalando dependencias del servidor..."
& $PipExe install flask flask-socketio eventlet Pillow mss

# -- Crear acceso directo en Start Menu --
$StartMenu = [Environment]::GetFolderPath("CommonStartMenu")
$ShortcutPath = Join-Path $StartMenu "Programs\VIGIA Server.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PythonExe
$Shortcut.Arguments = "`"$(Join-Path $ScriptDir 'vigia-launcher.py')`""
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.Description = "VIGIA - Panel del Profesor"
$IconPath = Join-Path $ScriptDir "img\logo2.ico"
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
}
$Shortcut.Save()
Write-Host "[OK] Acceso directo creado en Start Menu" -ForegroundColor Green

# -- Registrar tarea programada (auto-arranque) --
$TaskName = "VIGIA Server"
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$(Join-Path $ScriptDir 'server.py')`" 5000" -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -AtLogon
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
    Write-Host "[OK] Tarea programada '$TaskName' creada (auto-arranque al login)" -ForegroundColor Green
} catch {
    Write-Host "[!] No se pudo crear la tarea programada (se requieren permisos de administrador)" -ForegroundColor Yellow
}

# -- Abrir puerto 5000 en el firewall --
try {
    New-NetFirewallRule -DisplayName "VIGIA Server" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -ErrorAction SilentlyContinue | Out-Null
    Write-Host "[OK] Puerto 5000 abierto en el firewall" -ForegroundColor Green
} catch {
    Write-Host "[!] No se pudo abrir el puerto 5000 en el firewall" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Instalacion completada!" -ForegroundColor Green
Write-Host "  Ejecuta: $PythonExe vigia-launcher.py" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
