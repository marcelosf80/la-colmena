# Bitácora — La Colmena

Este documento no reemplaza `docs/arquitectura.md`, `docs/persistencia.md` ni
`docs/heartbeat-y-canal.md` — los complementa. Mientras esos explican *cómo*
funciona cada pieza, esta bitácora registra *en qué estado está el proyecto
hoy*, qué se verificó realmente y qué le falta contar a quien se sume
después. Se actualiza cada vez que el estado general cambia de forma
relevante (no en cada commit).

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

- **Resultado parcial/final de vuelta al coordinador**: hoy el nodo genera
  texto con `llama-server` y lo registra en su recibo local, pero esa
  respuesta no vuelve al coordinador por el canal WebSocket. Sin esto, el
  usuario que hizo la consulta original nunca ve la respuesta — es el
  gap más urgente para tener un flujo end-to-end real.
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
