# Compila (si hace falta) y corre un nodo de La Colmena en este PC.
#
# Uso mínimo (motor simulado, solo prueba la red, no genera texto real):
#   .\scripts\iniciar-nodo.ps1 -Coordinador "http://192.168.1.10:8000" -ModeloHash "llama3-8b-q4"
#
# Con inferencia real (ver docs/prueba-real.md para conseguir los archivos):
#   .\scripts\iniciar-nodo.ps1 -Coordinador "http://192.168.1.10:8000" -ModeloHash "llama3-8b-q4" `
#       -LlamaServer "C:\colmena\llama-server.exe" -Pesos "C:\colmena\modelos\llama3-8b-q4.gguf"

param(
    [string]$Coordinador = "http://localhost:8000",
    [string]$NodoId = "",
    [Parameter(Mandatory = $true)][string]$ModeloHash,
    [string]$LlamaServer = "",
    [string]$Pesos = "",
    [int]$RamMaxMb = 4096,
    [double]$CpuMaxPct = 50
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$nodo = Join-Path $raiz "nodo-escritorio"

if (-not (Test-Path $nodo)) {
    Write-Error "No se encontró la carpeta 'nodo-escritorio' junto a 'scripts'. Corré este script desde la raíz del repo clonado."
    exit 1
}

Set-Location $nodo

$cargo = Get-Command cargo -ErrorAction SilentlyContinue
if (-not $cargo) {
    Write-Error "No se encontró 'cargo'. Instalá Rust desde https://rustup.rs y abrí una terminal nueva."
    exit 1
}

if (-not $NodoId) {
    $NodoId = "$($env:COMPUTERNAME)-$(Get-Random -Maximum 9999)"
    Write-Host "No pasaste -NodoId, generé uno: $NodoId"
}

Write-Host "Compilando el nodo (la primera vez puede tardar varios minutos)..."
cargo build --release

$exe = Join-Path $nodo "target\release\nodo-escritorio.exe"
if (-not (Test-Path $exe)) {
    Write-Error "No se generó $exe. Revisá los errores de compilación de arriba."
    exit 1
}

$argumentos = @(
    "--coordinador", $Coordinador,
    "--nodo-id", $NodoId,
    "--modelo-hash", $ModeloHash,
    "--posicion", "0",
    "--ram-max-mb", $RamMaxMb,
    "--cpu-max-pct", $CpuMaxPct
)

if ($LlamaServer -and $Pesos) {
    if (-not (Test-Path $LlamaServer)) {
        Write-Error "No existe el archivo -LlamaServer: $LlamaServer"
        exit 1
    }
    if (-not (Test-Path $Pesos)) {
        Write-Error "No existe el archivo -Pesos: $Pesos"
        exit 1
    }
    $argumentos += @("--llama-server", $LlamaServer, "--pesos", $Pesos)
    Write-Host ""
    Write-Host "Inferencia REAL con llama-server: $LlamaServer"
    Write-Host "Modelo: $Pesos"
} else {
    Write-Host ""
    Write-Host "AVISO: no pasaste -LlamaServer y -Pesos juntos, así que este nodo corre"
    Write-Host "el motor SIMULADO (prueba el registro, el heartbeat y el despacho de"
    Write-Host "trabajo, pero no genera texto real). Ver docs/prueba-real.md para"
    Write-Host "conseguir llama-server.exe y un modelo .gguf chico."
}

Write-Host ""
Write-Host "==================================================================="
Write-Host " Nodo '$NodoId' conectando a $Coordinador"
Write-Host " Ctrl+C para detenerlo prolijamente (avisa al coordinador antes de salir)"
Write-Host "==================================================================="
Write-Host ""

& $exe @argumentos
