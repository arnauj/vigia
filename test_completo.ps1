# ============================================================================
# Test completo: simula arranque + abrir dashboard
# ============================================================================

Write-Host "=== TEST 1: Simular arranque (tarea programada via VBS) ===" -ForegroundColor Cyan
Stop-Process -Name "vigia-servidor" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "vigia-launcher" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "chrome" -Force -ErrorAction SilentlyContinue
Start-Sleep 2

# Ejecutar la tarea programada
schtasks.exe /Run /TN "VIGIA Server"
Start-Sleep 8

$srv = Get-Process -Name "vigia-servidor" -ErrorAction SilentlyContinue
if ($srv) {
    Write-Host "[OK] Servidor corriendo (PID $($srv.Id), ventana=$($srv.MainWindowHandle))" -ForegroundColor Green
    if ($srv.MainWindowHandle -eq 0) {
        Write-Host "[OK] SIN VENTANA VISIBLE" -ForegroundColor Green
    } else {
        Write-Host "[FALLO] TIENE VENTANA VISIBLE!" -ForegroundColor Red
    }
} else {
    Write-Host "[FALLO] Servidor NO corriendo" -ForegroundColor Red
}

$listening = Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "[OK] Puerto 5000 escuchando" -ForegroundColor Green
} else {
    Write-Host "[AVISO] Puerto 5000 no escucha aun" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== TEST 2: Abrir dashboard (launcher, como Menu Inicio) ===" -ForegroundColor Cyan
Start-Process "C:\Program Files\VIGIA Server\launcher\vigia-launcher.exe" -WorkingDirectory "C:\Program Files\VIGIA Server\launcher"
Start-Sleep 8

$chrome = Get-Process -Name "chrome" -ErrorAction SilentlyContinue
if ($chrome) {
    Write-Host "[OK] Chrome abierto (dashboard visible)" -ForegroundColor Green
} else {
    Write-Host "[FALLO] Chrome no se abrio" -ForegroundColor Red
}

$srv2 = Get-Process -Name "vigia-servidor" -ErrorAction SilentlyContinue
if ($srv2 -and $srv2.MainWindowHandle -eq 0) {
    Write-Host "[OK] Servidor sigue corriendo SIN ventana" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== RESUMEN ===" -ForegroundColor Yellow
Write-Host "Procesos VIGIA activos:"
Get-Process -Name "vigia-*" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  $($_.ProcessName) PID=$($_.Id) ventana=$($_.MainWindowHandle)"
}
