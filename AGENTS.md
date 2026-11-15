# AGENTS.md — La Colmena

Red P2P de cómputo compartido para IA. Dos componentes independientes, sin
monorepo tooling: `coordinador/` (Python/FastAPI) y `nodo-escritorio/` (Rust).
Todo el código, comentarios, docs y mensajes de commit van **en español**;
`CONTRIBUTING.md` permite inglés en comentarios de código si se mantiene
consistente dentro del archivo.

## Alcance real (no confundir con la visión)

- **No existe inferencia cooperativa por capas.** Cada nodo carga un modelo
  `.gguf` completo en `llama-server`; `cargar(capa_desde, capa_hasta)` solo
  valida y guarda el rango como metadato. El nodo procesa el `prompt` que
  viaja en la `asignacion` (`src/main.rs`), no una activación del nodo
  anterior. `--prompt-demo` es solo el respaldo cuando falta el prompt.
- La topología real es **réplicas de modelos completos**: el coordinador
  reparte consultas entre nodos que sirven el mismo modelo. No prometer en
  docs/README que se suma VRAM/RAM entre máquinas.
- La verificación por réplicas (dos cadenas independientes, comparación de
  texto exacto) existe pero está **apagada por defecto**
  (`COMUNIDAD_IA_TASA_VERIFICACION=0.0`): con sampling no determinístico dos
  nodos honestos pueden diferir.

## Comandos de verificación

Coordinador (desde `coordinador/`):

```bash
# Linux/macOS (CI usa Python 3.11)
python -m pytest tests/unitarios -v
# Windows (venv local, Python 3.14)
..\coordinador\.venv\Scripts\python -m pytest tests/unitarios -q
```

- Tests de integración Postgres: `pytest tests/integraciones -v`. Se **saltan**
  si `COMUNIDAD_IA_BD_URL` no está definida; en CI corren contra `postgres:17`.
  No hay Docker en esta máquina: no inventes una base local, verificalos en CI.
- Un solo test: `python -m pytest tests/unitarios/test_api.py::test_nombre -q`.

Nodo (desde `nodo-escritorio/`):

```bash
# Windows: cargo no está en PATH por defecto
$env:PATH="$env:USERPROFILE\.cargo\bin;$env:PATH"
cargo test
```

- CI usa `cargo test --locked`: si tocás `Cargo.toml`, actualizá `Cargo.lock`
  o el job falla.
- No hay lint/formatter/typecheck configurados; el gate es pytest + cargo test
  (más integración Postgres en CI).

## Arquitectura que no se ve en los nombres

- **Hexagonal**: el dominio (`app/dominio/`) no hace I/O. Los routers dependen
  de los `Protocol` async de `app/infraestructura/repositorios/base.py`, no de
  implementaciones.
- El repositorio se elige en el `lifespan` de `app/main.py`: Postgres si
  `COMUNIDAD_IA_BD_URL` tiene valor, memoria si no. Toda dependencia se expone
  por `app.state` y se inyecta con `app/api/dependencias.py`. Al cambiar un
  contrato hay que actualizar **memoria y Postgres**.
- Variables de entorno con prefijo `COMUNIDAD_IA_` (`app/config.py`):
  `BD_URL`, `LATIDO_TIMEOUT_S`, `TRABAJO_TIMEOUT_S`, `REINTENTO_COLA_S`,
  `TASA_VERIFICACION`.
- Esquema Postgres idempotente (`ESQUEMA_SQL` con `CREATE TABLE IF NOT
  EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, sin Alembic). Al
  agregar columnas: SQL, `guardar`/`obtener`, helper `_fila_a_*` y repo en
  memoria.
- El estado del nodo lo decide el servidor desde el heartbeat
  (`estado_efectivo`), no el cliente.
- El nodo abre `WS /ws/nodos/{id}` (una conexión por nodo; reconectar
  reemplaza la vieja). `GestorConexiones` vive en memoria y `despedir_nodo()`
  marca CAIDO al perder el canal.
- Ciclo de un trabajo: `EN_COLA` → `EN_CURSO` → (`VERIFICANDO` si hay
  réplica) → `COMPLETADO`/`FALLIDO`. Estados terminales son inmutables ante
  resultados tardíos.
  - El resultado vuelve **por el mismo WebSocket**:
    `{"tipo":"resultado","trabajo_id", "exito", "texto", "error", "rol"}`.
    `rol` es `primaria` o `verificacion`; el nodo solo lo repite.
  - `_vigilar_trabajos_vencidos` marca FALLIDO lo que supera
    `TRABAJO_TIMEOUT_S`; `_vigilar_cola` re-despacha `EN_COLA`
    replanificando con los candidatos actuales (`reintentar_cola`).
- El protocolo Protobuf (`packages/protocolo/esquemas/mensajes.proto`) **no
  está cableado**: el transporte real hoy es JSON sobre HTTP/WebSocket.

## Trampas conocidas

- `asyncpg` no infiere tipos en funciones SQL: castear siempre, p. ej.
  `to_timestamp($1::double precision)`, o falla con `AmbiguousFunctionError`
  solo contra Postgres real.
- `TestClient` de FastAPI no entrega el evento de desconexión de un WebSocket
  hasta salir del bloque `with cliente.websocket_connect(...)`. No asserts
  `CAIDO` dentro del mismo bloque; la lógica está en `despedir_nodo()` y se
  testea en `tests/unitarios/test_websockets.py`.
- `requirements.txt` está pinneado a versiones verificadas localmente. No
  bajar `starlette`: versiones viejas no entregan el disconnect del WS en CI.
- El nodo usa `minreq` (HTTP bloqueante) dentro de `spawn_blocking`, y
  `tungstenite` en un hilo propio con un canal para devolver resultados. No
  migrar a un stack async sin motivo.
- Inferencia real = binario oficial `llama-server` como proceso hijo
  (`src/motor_servidor.rs`) sobre HTTP local (puerto 8718 por defecto). Sin
  `--llama-server` + `--pesos` corre `MotorSimulado`; no hay FFI por diseño.
- Los pesos `.gguf` nunca viajan entre pares; cada nodo los baja del catálogo.

## Flujo de trabajo

- Repo público `marcelosf80/la-colmena`, rama `main`, CI en
  `.github/workflows/ci.yml` (jobs `coordinador` y `nodo-escritorio`).
- Antes de pushear: correr la suite del componente tocado. Si cambia el
  contrato JSON, actualizar coordinador, nodo y sus tests de serialización
  (`src/canal_trabajo.rs`, `src/cliente_coordinador.rs`).
- `docs/bitacora.md` registra el estado verificado y las limitaciones
  conocidas; leerla antes de asumir que algo está implementado.
- Docs: `docs/arquitectura.md`, `docs/persistencia.md`,
  `docs/heartbeat-y-canal.md`; contribución en `CONTRIBUTING.md`.
