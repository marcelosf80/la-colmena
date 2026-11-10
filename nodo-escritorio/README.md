# nodo-escritorio

Daemon en Rust que un usuario instala para donar recursos a la red. Se
conecta al coordinador, reporta su capacidad y (en Fase 1) recibe trabajo
para ejecutar con `llama.cpp`.

## Estado actual

Implementado y probado contra el coordinador FastAPI real:

- Registro inicial (`ClienteCoordinador::registrar`).
- Loop de heartbeat local con medición de RAM/CPU (`sysinfo`) y pausa
  automática si se excede la política donada.
- Máquina de estados de control de usuario (activo / pausado / deteniendo),
  lista para conectarse a una señal externa (hoy solo Ctrl+C).
- `MotorInferencia`: trait + implementación simulada. **Pendiente**: bindear
  `llama.cpp` real (ver sección siguiente).
- `recibo_local`: registro append-only de trabajo realizado, listo para
  conectarse cuando exista el loop de ejecución real.

## Pendiente para Fase 1

1. Reemplazar `MotorSimulado` por una implementación real sobre `llama.cpp`
   (crate `llama-cpp-2` o bindings FFI propios). Requiere compilar contra
   `libllama` — no se incluye en este esqueleto porque necesita pesos y
   toolchain C++ que no son parte de este entorno de desarrollo.
2. Reemplazar el heartbeat "solo log" por un heartbeat real al coordinador,
   y abrir el canal (WebSocket) por el que el coordinador despacha trabajo.
3. Benchmark real al conectar, en vez de reportar `tokens_por_segundo: 0.0`.
4. Conectar `recibo_local` al loop de ejecución real.

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
