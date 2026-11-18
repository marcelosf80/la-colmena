#!/usr/bin/env bash
# Compila (si hace falta) y corre un nodo de La Colmena en este PC.
#
# Uso mínimo (motor simulado, solo prueba la red, no genera texto real):
#   MODELO_HASH=llama3-8b-q4 COORDINADOR=http://192.168.1.10:8000 ./scripts/iniciar-nodo.sh
#
# Con inferencia real (ver docs/prueba-real.md para conseguir los archivos):
#   MODELO_HASH=llama3-8b-q4 COORDINADOR=http://192.168.1.10:8000 \
#   LLAMA_SERVER=./llama-server PESOS=./modelos/llama3-8b-q4.gguf \
#   ./scripts/iniciar-nodo.sh
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODO_DIR="$RAIZ/nodo-escritorio"

if [ ! -d "$NODO_DIR" ]; then
    echo "No se encontró la carpeta 'nodo-escritorio' junto a 'scripts'. Corré esto desde la raíz del repo clonado." >&2
    exit 1
fi

cd "$NODO_DIR"

COORDINADOR="${COORDINADOR:-http://localhost:8000}"
NODO_ID="${NODO_ID:-$(hostname 2>/dev/null || echo nodo)-$RANDOM}"
MODELO_HASH="${MODELO_HASH:-}"
LLAMA_SERVER="${LLAMA_SERVER:-}"
PESOS="${PESOS:-}"
RAM_MAX_MB="${RAM_MAX_MB:-4096}"
CPU_MAX_PCT="${CPU_MAX_PCT:-50}"

if ! command -v cargo &>/dev/null; then
    echo "No se encontró 'cargo'. Instalá Rust: https://rustup.rs (después abrí una terminal nueva)." >&2
    exit 1
fi

if [ -z "$MODELO_HASH" ]; then
    echo "Falta la variable MODELO_HASH. Ejemplo:" >&2
    echo "  MODELO_HASH=llama3-8b-q4 ./scripts/iniciar-nodo.sh" >&2
    exit 1
fi

echo "Compilando el nodo (la primera vez puede tardar varios minutos)..."
cargo build --release

EXE="./target/release/nodo-escritorio"
if [ ! -f "$EXE" ]; then
    echo "No se generó $EXE. Revisá los errores de compilación de arriba." >&2
    exit 1
fi

ARGS=(--coordinador "$COORDINADOR" --nodo-id "$NODO_ID" --modelo-hash "$MODELO_HASH" --posicion 0 --ram-max-mb "$RAM_MAX_MB" --cpu-max-pct "$CPU_MAX_PCT")

if [ -n "$LLAMA_SERVER" ] && [ -n "$PESOS" ]; then
    [ -f "$LLAMA_SERVER" ] || { echo "No existe LLAMA_SERVER=$LLAMA_SERVER" >&2; exit 1; }
    [ -f "$PESOS" ] || { echo "No existe PESOS=$PESOS" >&2; exit 1; }
    ARGS+=(--llama-server "$LLAMA_SERVER" --pesos "$PESOS")
    echo ""
    echo "Inferencia REAL con llama-server: $LLAMA_SERVER"
    echo "Modelo: $PESOS"
else
    echo ""
    echo "AVISO: no seteaste LLAMA_SERVER y PESOS juntos, así que este nodo corre"
    echo "el motor SIMULADO (prueba el registro, el heartbeat y el despacho de"
    echo "trabajo, pero no genera texto real). Ver docs/prueba-real.md para"
    echo "conseguir llama-server y un modelo .gguf chico."
fi

echo ""
echo "==================================================================="
echo " Nodo '$NODO_ID' conectando a $COORDINADOR"
echo " Ctrl+C para detenerlo prolijamente (avisa al coordinador antes de salir)"
echo "==================================================================="
echo ""

exec "$EXE" "${ARGS[@]}"
