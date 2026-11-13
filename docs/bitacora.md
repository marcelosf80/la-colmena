# Bitácora — La Colmena

Este documento no reemplaza `docs/arquitectura.md`, `docs/persistencia.md` ni
`docs/heartbeat-y-canal.md` — los complementa. Mientras esos explican *cómo*
funciona cada pieza, esta bitácora registra *en qué estado está el proyecto
hoy*, qué se verificó realmente y qué le falta contar a quien se sume
después. Se actualiza cada vez que el estado general cambia de forma
relevante (no en cada commit).

## 2026-11-12 (2) — Timeout de trabajos colgados

Cerró el pendiente que había quedado anotado al final de la entrada
anterior: si el nodo se cae (o pierde el canal) entre procesar una
asignación y mandar el `resultado`, el trabajo ya no queda `en_curso` para
siempre.

**Qué cambió**

- `dominio/trabajos.py::marcar_vencido` (función pura, mismo estilo que
  `aplicar_resultado`): si el trabajo sigue `EN_CURSO`, lo pasa a `FALLIDO`
  con `error = MENSAJE_TIMEOUT`. No toca `EN_COLA` a propósito — ver el
  docstring sobre por qué ese es un problema de cola/reintento, no de
  timeout.
- Nuevo vigilante `_vigilar_trabajos_vencidos` en `main.py`, corriendo cada
  `trabajo_timeout_s / 3`, exactamente el mismo patrón que el vigilante de
  heartbeats que ya existía (`_vigilar_latidos`).
- `RepositorioTrabajos` suma `marcar_vencidos(ahora_unix, timeout_s)` al
  protocolo, con implementación en memoria y Postgres (columna nueva
  `actualizado_en`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
- **Unifiqué** `TIMEOUT_TRABAJO_MS` (que ya existía en `rutas_usuarios.py`,
  pero no se usaba para nada más que informarle el valor al nodo) con la
  nueva config `trabajo_timeout_s`: ahora hay una sola fuente de verdad
  para "cuánto tiempo se le da a un trabajo", y el vigilante y el
  `timeout_ms` que ve el nodo nunca pueden desincronizarse.

**Verificación**

- Coordinador: **50 tests** pasan (44 + 6 nuevos: 4 de dominio, 2 de
  repositorios en memoria). Sumé 2 tests de integración Postgres más
  (quedan sin correr acá, los valida CI).
- Probé la app completa levantada con los dos vigilantes corriendo a la
  vez (heartbeats + trabajos vencidos) — arranca y atiende requests sin
  problema.
- **Importante sobre cómo testear esto**: a diferencia de los nodos
  (`actualizar_latido` recibe un `momento_unix` explícito, así que los
  tests pueden usar timestamps sintéticos chicos como `1_100.0`), `Trabajo`
  no tiene un campo de timestamp propio — `guardar()` estampa el reloj real
  internamente. Los tests de este timeout usan `time.time()` + offset, no
  epochs sintéticos. Si alguien agrega más tests de vigilante acá, que siga
  ese patrón o va a fallar de forma confusa (todo "vencido" o nada, según
  si el offset sintético cae antes o después del Unix epoch real).

**Pendiente que queda**

- El nodo no sabe que su trabajo venció del lado del coordinador — si
  vuelve a conectarse y manda el `resultado` tarde, `aplicar_resultado` ya
  lo ignora (está en estado terminal), pero el nodo gastó cómputo real en
  un trabajo que nadie va a leer. No es grave, pero vale la pena que el
  nodo tenga su propio timeout local coherente con `timeout_ms`.
- Sigue sin existir la cola con reintento (ver entrada de 2026-11-11): un
  trabajo que nunca se pudo despachar porque no había nodo conectado queda
  `en_cola` sin que nada vuelva a intentarlo.

## 2026-11-12 — Resultado de vuelta al coordinador

Se cerró el gap que la entrada anterior marcaba como más urgente: ahora la
respuesta generada por el nodo **vuelve al coordinador** por el mismo
WebSocket y el usuario la lee con `GET /consultas/{trabajo_id}`.

**Qué cambió**

- Coordinador: `Trabajo` suma `texto_resultado` y `error`;
  `dominio/trabajos.py::aplicar_resultado` (función pura, idempotente sobre
  estados terminales); `api/websockets.py` despacha el mensaje `resultado`
  a `_procesar_resultado`; Postgres suma las columnas (`ALTER TABLE ... ADD
  COLUMN IF NOT EXISTS`, aplica solo en bases existentes al arrancar).
- Nodo: `canal_trabajo.rs` pasó a ser **bidireccional**. `iniciar` devuelve
  además un `Sender<MensajeResultado>`; el hilo del socket usa timeout de
  lectura de 200 ms para alternar entre vaciar la cola de salida y leer.
  `main.rs` envía `exitoso`/`fallido` tras cada asignación.

**Verificación**

- Coordinador: **44 tests** pasan (35 + 9 nuevos).
- Nodo: **35 tests** pasan (32 + 3 nuevos), compilado en una copia
  descartable con `url`/`idna`/`encoding_rs` fijados (ver deuda técnica #4
  de la entrada anterior; el `Cargo.toml`/`Cargo.lock` del repo no se
  tocaron).
- **Prueba end-to-end real** (coordinador en memoria + binario del nodo con
  motor simulado): consulta → `en_curso` → `completado` con
  `texto_resultado` correcto.
- **No verificado**: el flujo con `llama-server` real (no hay binario ni
  pesos en el entorno de desarrollo) y los tests de integración contra
  Postgres real (los corre CI). Conviene mirar el resultado de CI.

**Deuda / pendiente que queda**

- El resultado hoy es siempre "final": en una cadena de varios nodos cada
  uno procesa el prompt por su cuenta y reporta. Falta el pipeline real
  (reenviar la activación a `siguiente_nodo_id`, solo el último reporta).
- El timeout de lectura de 200 ms solo se aplica en `ws://` (variante
  `Plain`); con `wss://` el hilo volvería a leer bloqueante y los resultados
  esperarían al próximo mensaje entrante. Resolver antes de usar TLS.
- ~~Si el nodo se cae entre procesar y enviar, el resultado se pierde y el
  trabajo queda `en_curso` para siempre~~: **resuelto el 2026-11-12 (2)**,
  ver la entrada de arriba (vigilante de timeout).

## 2026-11-11 — Relevamiento de estado

El proyecto avanzó en paralelo en dos frentes de trabajo (este repo llegó
con bastante más implementado de lo que figuraba en una sesión de diseño
anterior). Esta entrada documenta el estado tal como quedó verificado hoy,
corriendo el código real, no repitiendo lo que dicen otros documentos.

### Qué se verificó hoy

| Componente | Verificación | Resultado |
|---|---|---|
| `coordinador/` | `pytest tests/unitarios -v` | **35 tests, todos pasan** (ver nota de badges abajo) |
| `nodo-escritorio/` | Lectura de código + conteo de `#[test]` | **32 tests** en el código fuente (coincide con lo que dice el README) |
| `nodo-escritorio/` | `cargo test` | **No se pudo correr en este entorno** — ver "Deuda técnica" |

### Mapa de arquitectura (verificado por lectura directa de código)

**Coordinador** (`coordinador/app/`):

```
dominio/          creditos.py, heartbeat.py, nodos.py, planificador.py, trabajos.py
api/              dependencias.py, rutas_nodos.py, rutas_usuarios.py, websockets.py
infraestructura/  repositorios/{base.py, candidatos.py, postgres.py}
```

- `dominio/heartbeat.py` decide el estado del nodo (CONECTADO/OCUPADO/CAIDO)
  a partir de lo que reporta — el nodo no se autodeclara CAIDO, lo decide
  el coordinador. Documentado con más detalle en `heartbeat-y-canal.md`.
- `infraestructura/repositorios/base.py` define los `Protocol` que separan
  dominio de persistencia; hay dos implementaciones intercambiables
  (memoria y Postgres vía `asyncpg`), ambas cumpliendo la misma interfaz.
- `api/websockets.py` + `api/dependencias.py`: el canal de despacho de
  trabajo y la inyección de dependencias de FastAPI.

**Nodo de escritorio** (`nodo-escritorio/src/`):

```
cliente_coordinador.rs   registro + heartbeat HTTP
canal_trabajo.rs         WebSocket: recibe asignaciones del coordinador
motor_servidor.rs        inferencia REAL vía `llama-server` como subprocess
ejecutor_modelo.rs       trait MotorInferencia (contrato compartido)
politicas_recursos.rs    límites de RAM/CPU donados
control_usuario.rs       máquina de estados activo/pausado/deteniendo
recibo_local.rs          registro local append-only de trabajo hecho
```

- **Decisión de diseño relevante que no estaba en la sesión de diseño
  original**: la inferencia real NO usa bindings FFI a `llama.cpp`. Usa el
  binario oficial `llama-server` como proceso hijo, hablándole por HTTP
  local (`/health`, `/completion`). Ventaja documentada en el propio
  archivo: cero toolchain C++ para el usuario final, aislamiento de
  memoria, protocolo estable. Es una elección sólida — evita la fricción
  de compilar `llama.cpp` en la máquina de cada usuario.

### Deuda técnica encontrada (para que no se pierda)

1. **`CONTRIBUTING.md` tiene números de tests desactualizados**: dice "los
   12 tests deben pasar" (coordinador) y "los 21 tests deben pasar" (nodo).
   Los números reales hoy son **35 y 32** respectivamente. Lo corregí en
   este mismo commit.
2. **El badge de tests del README dice "31"**, también desactualizado
   (son 35). Lo corregí también.
3. **Warning de deprecación**: `starlette.testclient` avisa que usar
   `httpx` con él está deprecado y sugiere `httpx2`. No rompe nada hoy,
   pero conviene resolverlo antes de que `httpx` deje de soportarlo.
4. **El `Cargo.lock` del nodo quedó en formato v4**, que requiere Rust
   relativamente reciente (más nuevo que 1.78). Esto es correcto para
   desarrollo normal (`rustup install stable` lo maneja sin problema) y es
   lo que CI usa (`dtolnay/rust-toolchain@stable`). El problema es
   específico de este entorno de verificación, que solo tiene `rustc 1.75`
   vía `apt` de Ubuntu — no pude correr `cargo test` acá sin re-pinear
   dependencias manualmente (ya pasó antes con `tokio`, `rayon`, `clap`;
   ahora se sumarían más por `tungstenite`). **No toqué el `Cargo.lock`
   real** para no romper lo que CI ya valida con Rust moderno. Cualquiera
   que clone el repo con Rust estable actual no debería ver este problema.

### Qué falta (repite la hoja de ruta del README, pero con contexto de por qué importa cada ítem)

- ~~**Resultado de vuelta al coordinador**~~: **resuelto el 2026-11-12**
  (ver entrada de arriba). Queda el pipeline multi-nodo real.
- **Cola con reintento**: si el nodo asignado no tiene canal abierto, el
  trabajo queda `en_cola` sin mecanismo de reintento automático.
- **Verificación por réplicas**: sigue pendiente el gap de seguridad más
  importante señalado en la auditoría original — sin esto, un nodo
  malicioso puede devolver resultados alterados sin que se note.
- **Nodo Android** (Kotlin): no se empezó.
- **Descentralización del coordinador**: discusión abierta, sin resolver.

### Cómo seguir si sos otro desarrollador llegando a este repo

1. Empezá por `README.md` (visión general y cómo levantar todo).
2. `docs/arquitectura.md` para el modelo de dominio del coordinador.
3. `docs/persistencia.md` si vas a tocar algo de base de datos.
4. `docs/heartbeat-y-canal.md` si vas a tocar el protocolo nodo↔coordinador.
5. Esta bitácora, para saber qué está realmente probado y qué deuda hay
   pendiente de limpiar.
6. Si vas a atacar el gap de "resultado de vuelta al coordinador": mirá
   primero `canal_trabajo.rs` (lado nodo) y `api/websockets.py` +
   `dominio/trabajos.py` (lado coordinador) — ahí está el contrato a
   extender.
