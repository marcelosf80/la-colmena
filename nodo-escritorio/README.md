# nodo-escritorio

Daemon en Rust que un usuario instala para donar recursos a la red. Se
conecta al coordinador, reporta su capacidad y recibe trabajo para ejecutar
con `llama.cpp`.

> **Alcance actual:** cada nodo carga el **modelo completo** y lo ejecuta
> localmente. No hay particionado por capas ni suma de VRAM/RAM entre
> máquinas; la red reparte consultas entre réplicas del mismo modelo.

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
- **Canal WebSocket bidireccional** (`canal_trabajo`): hilo bloqueante con
  `tungstenite`, reconexión automática cada 5 s; recibe asignaciones y devuelve
  `{"tipo":"resultado", ...}` por el mismo canal (incluye el `rol`
  `primaria`/`verificacion` que envió el coordinador).
- **Inferencia real opcional** con `llama-server` como proceso hijo
  (`MotorServidorLlama`); sin binario/pesos usa `MotorSimulado` (dev/CI).
- Máquina de estados de control de usuario (activo / pausado / deteniendo).
- `recibo_local`: registro append-only del trabajo realizado con los tokens
  reportados por el motor.

## Pendiente conocido

1. ~~Prompt real por asignación~~: la asignación ya trae `prompt`; el nodo lo
   ejecuta y usa `--prompt-demo` solo como respaldo si falta.
2. Benchmark real al conectar, en vez de reportar `tokens_por_segundo: 0.0`
   (y `tiene_gpu: false` fijo).
3. Cancelación/timeout local: si el coordinador marca el trabajo FALLIDO, el
   nodo puede seguir consumiendo recursos.
4. Descarga automática del binario `llama-server` y los pesos `.gguf` desde el
   catálogo oficial (hoy se indican por CLI).

## Nota sobre versiones de dependencias

`Cargo.toml` mantiene pines puntuales por compatibilidad con un entorno
histórico que traía `rustc 1.75` (las releases nuevas de `tokio`, `rayon` y
`clap` requieren Rust 2024). El CI usa Rust estable y compila con
`cargo test --locked`. Si tu entorno usa estable actual, podés proponer un PR
para quitar los pines.

También se usa `minreq` en vez de `reqwest` para HTTP: es bloqueante, con muy
pocas dependencias y un binario final más liviano. Las llamadas se delegan a
`spawn_blocking` para no frenar el runtime async.

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

39 tests cubriendo: políticas de recursos, máquina de estados de control de
usuario, contrato de serialización del canal (asignación/resultado), motor
simulado, cliente HTTP del coordinador y registro local de recibos.
