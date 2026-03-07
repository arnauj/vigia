param(
    [ValidateSet('all', 'server', 'client')]
    [string]$Target = 'all',
    [switch]$SkipInstaller,
    [switch]$KeepPortableApps
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if ([System.Environment]::OSVersion.Platform -ne 'Win32NT') {
    throw 'build_windows.ps1 debe ejecutarse en Windows.'
}

$version = '1.1'
$distRoot = Join-Path $projectRoot 'dist/windows'
$buildRoot = Join-Path $distRoot 'build'
$specRoot = Join-Path $buildRoot 'spec'
$binRoot = Join-Path $distRoot 'bin'
$installerRoot = Join-Path $distRoot 'installers'

New-Item -ItemType Directory -Force -Path $distRoot, $buildRoot, $specRoot, $binRoot, $installerRoot | Out-Null

function Step([string]$msg) {
    Write-Host "[VIGIA] $msg" -ForegroundColor Cyan
}

function Build-App {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Entry,
        [string[]]$AddData = @()
    )

    Step "Compilando $Name..."

    $targetDist = Join-Path $binRoot $Name
    if (Test-Path $targetDist) {
        Remove-Item -Recurse -Force $targetDist
    }

    $args = @(
        '-m', 'PyInstaller',
        '--noconfirm',
        '--clean',
        '--noconsole',
        '--name', $Name,
        '--distpath', $binRoot,
        '--workpath', $buildRoot,
        '--specpath', $specRoot
    )

    foreach ($data in $AddData) {
        $args += @('--add-data', $data)
    }

    $args += $Entry

    & python @args
}

function Find-Iscc {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        "$env:ProgramFiles(x86)\\Inno Setup 6\\ISCC.exe",
        "$env:ProgramFiles\\Inno Setup 6\\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

Step 'Instalando dependencias base de build...'
python -m pip install --upgrade pip pyinstaller

if ($Target -in @('all', 'server')) {
    Step 'Instalando dependencias del servidor...'
    python -m pip install -r requirements_servidor.txt
    Build-App -Name 'VIGIA-Server' -Entry 'server.py' -AddData @('templates;templates', 'img;img')
}

if ($Target -in @('all', 'client')) {
    Step 'Instalando dependencias del cliente...'
    python -m pip install -r requirements_cliente.txt
    Build-App -Name 'VIGIA-Client' -Entry 'client.py'
}

if (-not $SkipInstaller) {
    $iscc = Find-Iscc
    if ($iscc) {
        Step "Inno Setup detectado en: $iscc"
        $builtInstaller = $false
        if ($Target -in @('all', 'server')) {
            Step 'Generando instalador EXE del servidor...'
            & $iscc "/DSourceDir=$($binRoot)\\VIGIA-Server" "/DOutputDir=$installerRoot" "/DAppVersion=$version" "windows\\installer_server.iss"
            $builtInstaller = $true
        }
        if ($Target -in @('all', 'client')) {
            Step 'Generando instalador EXE del cliente...'
            & $iscc "/DSourceDir=$($binRoot)\\VIGIA-Client" "/DOutputDir=$installerRoot" "/DAppVersion=$version" "windows\\installer_client.iss"
            $builtInstaller = $true
        }
        if ($builtInstaller -and -not $KeepPortableApps -and (Test-Path $binRoot)) {
            Step 'Eliminando ejecutables portables intermedios (quedan solo los 2 instaladores)...'
            Remove-Item -Recurse -Force $binRoot
        }
    }
    else {
        Write-Warning 'Inno Setup no encontrado. Se generaron solo las apps en dist/windows/bin/.'
        Write-Warning 'Instala Inno Setup 6 y vuelve a ejecutar build_windows.ps1 para obtener instaladores .exe.'
    }
}

Step 'Proceso finalizado.'
if (Test-Path $binRoot) {
    Write-Host "Binarios: $binRoot"
}
Write-Host "Instaladores: $installerRoot"
