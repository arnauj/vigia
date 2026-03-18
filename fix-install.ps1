# ============================================================================
# VIGIA - Fix de instalacion: corrige consola visible y configura todo
# Se auto-eleva a administrador si no lo es
# ============================================================================

$ErrorActionPreference = "Stop"

# --- Auto-elevar a admin ---
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$srcDir = Split-Path -Parent $PSCommandPath
$logFile = Join-Path $srcDir "fix-install.log"
Start-Transcript -Path $logFile -Force

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  VIGIA - Corrigiendo instalacion" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# ============================================================
# 1. SERVIDOR: reemplazar exe viejo y corregir todo
# ============================================================
$serverInstall = "C:\Program Files\VIGIA Server"
if (Test-Path $serverInstall) {
    Write-Host ""
    Write-Host "[1] Arreglando servidor..." -ForegroundColor Yellow

    # Matar procesos viejos
    Stop-Process -Name "vigia-servidor" -Force -ErrorAction SilentlyContinue
    Stop-Process -Name "vigia-launcher" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    # Copiar el exe nuevo (GUI, sin consola) encima del viejo en la raiz
    $newExe = Join-Path $serverInstall "server\vigia-servidor.exe"
    $oldExe = Join-Path $serverInstall "vigia-servidor.exe"
    if (Test-Path $newExe) {
        Copy-Item $newExe $oldExe -Force
        Write-Host "  [OK] Exe raiz reemplazado con version GUI (sin consola)" -ForegroundColor Green
    }

    # Eliminar tarea programada rota
    schtasks /Delete /TN "VIGIA Server" /F 2>$null
    Write-Host "  [OK] Tarea programada vieja eliminada" -ForegroundColor Green

    # Crear tarea programada correcta: wscript + VBS (CERO consola)
    $vbsPath = Join-Path $serverInstall "vigia-servidor-silent.vbs"
    if (Test-Path $vbsPath) {
        # Usar PowerShell para crear la tarea (mejor manejo de rutas con espacios)
        $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`" --no-browser" -WorkingDirectory $serverInstall
        $trigger = New-ScheduledTaskTrigger -AtLogon
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName "VIGIA Server" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
        Write-Host "  [OK] Tarea programada creada: wscript -> VBS -> exe GUI (sin consola)" -ForegroundColor Green
    } else {
        Write-Host "  [!] No se encontro vigia-servidor-silent.vbs" -ForegroundColor Red
    }

    # Corregir acceso directo del Start Menu -> apuntar al launcher
    $launcherExe = Join-Path $serverInstall "launcher\vigia-launcher.exe"
    $startMenuLink = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\VIGIA\VIGIA Server.lnk"
    if ((Test-Path $launcherExe) -and (Test-Path (Split-Path $startMenuLink))) {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($startMenuLink)
        $shortcut.TargetPath = $launcherExe
        $shortcut.Arguments = ""
        $shortcut.WorkingDirectory = Join-Path $serverInstall "launcher"
        $shortcut.Description = "VIGIA - Panel del Profesor"
        $icoPath = Join-Path $serverInstall "server\img\logo2.ico"
        if (Test-Path $icoPath) { $shortcut.IconLocation = $icoPath }
        $shortcut.Save()
        Write-Host "  [OK] Start Menu -> launcher (abre dashboard, sin consola)" -ForegroundColor Green
    }

    # Corregir acceso directo del escritorio si existe
    $desktopLink = "C:\Users\Public\Desktop\VIGIA Server.lnk"
    if (Test-Path $desktopLink) {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($desktopLink)
        $shortcut.TargetPath = $launcherExe
        $shortcut.Arguments = ""
        $shortcut.WorkingDirectory = Join-Path $serverInstall "launcher"
        $shortcut.Description = "VIGIA - Panel del Profesor"
        if (Test-Path $icoPath) { $shortcut.IconLocation = $icoPath }
        $shortcut.Save()
        Write-Host "  [OK] Desktop -> launcher (sin consola)" -ForegroundColor Green
    }

    Write-Host "  [OK] Servidor corregido" -ForegroundColor Green
}

# ============================================================
# 2. CLIENTE: instalar si existe en Program Files
# ============================================================
$clientInstall = "C:\Program Files\VIGIA Client"
$clientDist = Join-Path $srcDir "dist\windows\vigia-cliente"
$clientVbs = Join-Path $srcDir "vigia-cliente-silent.vbs"

if (Test-Path $clientInstall) {
    Write-Host ""
    Write-Host "[2] Arreglando cliente instalado..." -ForegroundColor Yellow

    Stop-Process -Name "vigia-cliente" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1

    # Copiar nuevos ejecutables
    if (Test-Path $clientDist) {
        Copy-Item "$clientDist\*" $clientInstall -Recurse -Force
        Write-Host "  [OK] Ejecutables del cliente actualizados (GUI, sin consola)" -ForegroundColor Green
    }

    # Copiar VBS
    if (Test-Path $clientVbs) {
        Copy-Item $clientVbs $clientInstall -Force
        Write-Host "  [OK] VBS wrapper copiado" -ForegroundColor Green
    }

    # Leer IP del servidor desde config
    $configFile = Join-Path $env:APPDATA "vigia\client.conf"
    $serverIP = "192.168.1.2"
    if (Test-Path $configFile) {
        $serverIP = (Get-Content $configFile -Raw).Trim()
    }

    # Crear/actualizar shortcut en Startup -> wscript + VBS
    $startupDir = [Environment]::GetFolderPath("Startup")
    $startupLink = Join-Path $startupDir "VIGIA Client.lnk"
    $vbsDst = Join-Path $clientInstall "vigia-cliente-silent.vbs"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($startupLink)
    $shortcut.TargetPath = "wscript.exe"
    $shortcut.Arguments = "`"$vbsDst`" $serverIP"
    $shortcut.WorkingDirectory = $clientInstall
    $shortcut.Description = "VIGIA - Cliente del Alumno"
    $icoClient = Join-Path $clientInstall "img\logo2.ico"
    if (Test-Path $icoClient) { $shortcut.IconLocation = $icoClient }
    $shortcut.Save()
    Write-Host "  [OK] Startup -> wscript + VBS (sin consola)" -ForegroundColor Green

    Write-Host "  [OK] Cliente corregido" -ForegroundColor Green
} elseif (Test-Path $clientDist) {
    Write-Host ""
    Write-Host "[2] Cliente no instalado en Program Files, instalando..." -ForegroundColor Yellow

    New-Item -ItemType Directory -Path $clientInstall -Force | Out-Null
    Copy-Item "$clientDist\*" $clientInstall -Recurse -Force
    if (Test-Path $clientVbs) { Copy-Item $clientVbs $clientInstall -Force }
    Write-Host "  [OK] Cliente copiado a $clientInstall" -ForegroundColor Green
}

# ============================================================
# 3. Verificacion final
# ============================================================
Write-Host ""
Write-Host "=== VERIFICACION ===" -ForegroundColor Cyan

function Get-Sub { param($p); $b=[System.IO.File]::ReadAllBytes($p); $pe=[BitConverter]::ToInt32($b,60); [BitConverter]::ToUInt16($b,$pe+92) }

$exeRoot = "C:\Program Files\VIGIA Server\vigia-servidor.exe"
if (Test-Path $exeRoot) {
    $s = Get-Sub $exeRoot
    $t = if ($s -eq 2) { "GUI (SIN CONSOLA) - OK" } else { "CONSOLA - FALLO" }
    Write-Host "  Exe raiz servidor: $t" -ForegroundColor $(if ($s -eq 2) { "Green" } else { "Red" })
}

$exeClient = "C:\Program Files\VIGIA Client\vigia-cliente.exe"
if (Test-Path $exeClient) {
    $s = Get-Sub $exeClient
    $t = if ($s -eq 2) { "GUI (SIN CONSOLA) - OK" } else { "CONSOLA - FALLO" }
    Write-Host "  Exe cliente: $t" -ForegroundColor $(if ($s -eq 2) { "Green" } else { "Red" })
}

try {
    $task = Get-ScheduledTask -TaskName "VIGIA Server" -ErrorAction Stop
    $a = $task.Actions[0]
    Write-Host "  Tarea programada: $($a.Execute) $($a.Arguments)" -ForegroundColor Green
} catch {
    Write-Host "  Tarea programada: NO ENCONTRADA" -ForegroundColor Red
}

$startMenuLink = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\VIGIA\VIGIA Server.lnk"
if (Test-Path $startMenuLink) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($startMenuLink)
    Write-Host "  Start Menu servidor: $($s.TargetPath)" -ForegroundColor Green
}

$startupLink = Join-Path ([Environment]::GetFolderPath("Startup")) "VIGIA Client.lnk"
if (Test-Path $startupLink) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($startupLink)
    Write-Host "  Startup cliente: $($s.TargetPath) $($s.Arguments)" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Correccion completada!" -ForegroundColor Green
Write-Host "  - Servidor: se inicia sin consola al login" -ForegroundColor Green
Write-Host "  - Dashboard: se abre desde Start Menu sin consola" -ForegroundColor Green
Write-Host "  - Cliente: se inicia sin consola al login" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green

Stop-Transcript
Write-Host ""
Write-Host "Presiona Enter para cerrar..." -ForegroundColor Gray
Read-Host
