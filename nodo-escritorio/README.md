# nodo-escritorio

Daemon en Rust que un usuario instala para donar recursos a la red. Se
conecta al coordinador, reporta su capacidad y (en Fase 1) recibe trabajo
para ejecutar con `llama.cpp`.

## Inferencia real (llama.cpp)

El nodo ejecuta inferencia **real** usando el binario oficial `llama-server`
de [llama.cpp](https://github.com/ggml-org/llama.cpp) como proceso hijo:

```bash
# 1. Descargá el binario llama-server para tu plataforma desde las releases
#    de llama.cpp, y los pesos .gguf del modelo que quieras servir.

# 2. Corré el nodo con inferencia real:
./target/release/nodo-escritorio \
  --coordinador http://localhost:8000 \
  --nodo-id mi-nodo-1 \
  --modelo-hash <hash-del-modelo> \
  --posicion 0 \
  --pesos C:\modelos\qwen2.5-0.5b-q4_0.gguf \
  --llama-server C:\herramientas\llama-server.exe
```

- El motor escucha en `127.0.0.1:8718` (`--puerto-motor`) y el nodo le
  habla por HTTP local; los pesos nunca viajan entre pares.
- Los tokens generados quedan en el recibo local (`recibos-colmena.log`).
- Sin `--llama-server`/`--pesos`, el nodo corre con `MotorSimulado` (dev/CI).
- Por qué subprocess y no FFI: cero toolchain C++ para el usuario y
  aislamiento de memoria. El bind FFI (`llama-cpp-2`) queda documentado
  como alternativa si algún día se necesita latencia extra.

## Estado actual

Implementado y probado contra el coordinador FastAPI real:

- Registro inicial (`ClienteCoordinador::registrar`).
- **Heartbeat real cada 10 s** al coordinador (`POST /nodos/{id}/heartbeat`)
  con medición de RAM/CPU (`sysinfo`); al pausar (usuario o política de
  recursos) informa `acepta_trabajo: false` para que el coordinador deje de
  asignarle trabajo.
- **Canal WebSocket de despacho** (`canal_trabajo`): hilo bloqueante con
  `tungstenite`, reconexión automática con backoff de 5 s; las asignaciones
  llegan al loop principal por `mpsc` y quedan registradas en `recibo_local`.
- Máquina de estados de control de usuario (activo / pausado / deteniendo).
- `MotorInferencia`: trait + implementación simulada. **Pendiente**: bindear
  `llama.cpp` real (ver sección siguiente).
- `recibo_local`: registro append-only de trabajo realizado, ya conectado
  al loop de despacho.

## Pendiente para Fase 1

1. Envío de `ResultadoParcial`/`ResultadoFinal` por el canal (hoy el nodo
   ejecuta y registra el recibo local; no devuelve activaciones al
   siguiente nodo).
2. Benchmark real al conectar, en vez de reportar `tokens_por_segundo: 0.0`.
3. Descarga automática del binario `llama-server` y los pesos .gguf desde
   el catálogo oficial (hoy se indican por CLI).

## Nota sobre versiones de dependencias

Este entorno de desarrollo trae `rustc 1.75` vía `apt` (Ubuntu 24.04). Varias
dependencias (`tokio`, `rayon`, `clap`) tuvieron que fijarse a versiones
puntuales porque sus releases más recientes requieren Rust 2024 (rustc
1.85+). **En un entorno real, usar Rust estable actual (`rustup install
stable`) y quitar estos pines** — quedan documentados en `Cargo.toml` para
que no se pierda el motivo si alguien los ve y no entiende por qué están
fijados a versiones específicas en vez de rangos abiertos.

También se usa `minreq` en vez de `reqwest`: es un cliente HTTP bloqueante
con muy pocas dependencias, lo que evita tanto el problema de versiones
anterior como un binario final más pesado. Para WebSocket (Fase 1) se
evaluará `tokio-tungstenite`.

## Compilar y correr

```bash
cargo build --release
./target/release/nodo-escritorio \
  --coordinador http://localhost:8000 \
  --nodo-id mi-nodo-1 \
  --modelo-hash <hash-del-modelo> \
  --posicion 0 \
  --ram-max-mb 4096 \
  --cpu-max-pct 50
```

## Tests

```bash
cargo test
```

21 tests cubriendo: políticas de recursos, máquina de estados de control de
usuario, contrato de serialización con el coordinador, motor de inferencia
(stub) y el registro local de recibos.
