# Levanta el coordinador de La Colmena en este PC, accesible desde la red
# local (para que nodos en otras máquinas se puedan conectar).
#
# Uso: desde la carpeta del repo, en PowerShell:
#   .\scripts\iniciar-coordinador.ps1

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$coordinador = Join-Path $raiz "coordinador"

if (-not (Test-Path $coordinador)) {
    Write-Error "No se encontró la carpeta 'coordinador' junto a 'scripts'. Corré este script desde la raíz del repo clonado."
    exit 1
}

Set-Location $coordinador

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "No se encontró 'python' en el PATH. Instalá Python 3.11+ desde https://www.python.org/downloads/ y marcá 'Add python.exe to PATH' durante la instalación. Después abrí una terminal nueva."
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creando entorno virtual (solo la primera vez)..."
    python -m venv .venv
}

& .\.venv\Scripts\Activate.ps1

Write-Host "Instalando dependencias..."
pip install -q -r requirements.txt

# IP de la red local, para saber qué URL darle a un nodo que corra en OTRA PC.
$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceAlias -notmatch "Loopback" -and $_.IPAddress -notlike "169.254*" } |
    Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "==================================================================="
Write-Host " Coordinador de La Colmena — puerto 8000"
Write-Host ""
Write-Host " Desde ESTA PC:              http://localhost:8000"
if ($ip) {
    Write-Host " Desde OTRAS PCs de tu red:   http://${ip}:8000"
    Write-Host "   (esa es la URL que va en -Coordinador al correr un nodo en otra máquina)"
} else {
    Write-Host " No pude detectar tu IP de red local. Corré 'ipconfig' y buscá 'Dirección IPv4'."
}
Write-Host ""
Write-Host " Si Windows pregunta por el Firewall, permití el acceso en redes privadas"
Write-Host " (si no, los nodos de otras PCs no van a poder conectarse)."
Write-Host "==================================================================="
Write-Host ""

uvicorn app.main:app --host 0.0.0.0 --port 8000
