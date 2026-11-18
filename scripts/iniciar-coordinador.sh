#!/usr/bin/env bash
# Levanta el coordinador de La Colmena en este PC, accesible desde la red
# local (para que nodos en otras máquinas se puedan conectar).
#
# Uso: desde la raíz del repo clonado:
#   ./scripts/iniciar-coordinador.sh
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COORDINADOR_DIR="$RAIZ/coordinador"

if [ ! -d "$COORDINADOR_DIR" ]; then
    echo "No se encontró la carpeta 'coordinador' junto a 'scripts'. Corré esto desde la raíz del repo clonado." >&2
    exit 1
fi

cd "$COORDINADOR_DIR"

if ! command -v python3 &>/dev/null; then
    echo "No se encontró 'python3'. Instalá Python 3.11+ antes de seguir." >&2
    exit 1
fi

if [ ! -d .venv ]; then
    echo "Creando entorno virtual (solo la primera vez)..."
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Instalando dependencias..."
pip install -q -r requirements.txt

# IP de la red local, para saber qué URL darle a un nodo en OTRA PC.
IP=""
if command -v hostname &>/dev/null; then
    IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi
if [ -z "$IP" ] && command -v ip &>/dev/null; then
    IP="$(ip -4 addr show scope global 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1 || true)"
fi

echo ""
echo "==================================================================="
echo " Coordinador de La Colmena — puerto 8000"
echo ""
echo " Desde esta PC:              http://localhost:8000"
if [ -n "$IP" ]; then
    echo " Desde otras PCs de tu red:   http://$IP:8000"
    echo "   (esa es la URL que va en --coordinador al correr un nodo en otra máquina)"
else
    echo " No pude detectar tu IP de red local — probá 'ip addr' o 'ifconfig'."
fi
echo ""
echo " Si tenés un firewall activo (ufw, firewalld), puede que tengas que"
echo " abrir el puerto 8000 para que otras PCs se conecten:"
echo "   sudo ufw allow 8000/tcp"
echo "==================================================================="
echo ""

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
