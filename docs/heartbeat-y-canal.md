# Heartbeat y canal de trabajo

Cómo los nodos comunican su estado y reciben asignaciones.

## Diagrama del ciclo

```text
Nodo (Rust)                          Coordinador (FastAPI)
     │  POST /nodos/registro             │
     │──────────────────────────────────►│  guarda nodo + candidato
     │  WS /ws/nodos/{nodo_id}           │
     │═══════════════════════════════════►│  registra conexión
     │  POST /nodos/{id}/heartbeat        │
     │──────────────────────────────────►│  cada 10 s: estado + carga
     │◄──────────────────────────────────│  vigilante marca CAIDOS (>30 s)
     │  WS: {"tipo":"asignacion", ...}    │
     │◄──────────────────────────────────│  al armar una cadena
     │  (motor sim. procesa + recibo)     │
     │  WS: {"tipo":"latido", ...}        │
     │──────────────────────────────────►│  latido alternativo por canal
```

## Endpoints y mensajes

### Heartbeat HTTP (canal principal del nodo de escritorio)

`POST /nodos/{nodo_id}/heartbeat`

```json
{
  "consultas_en_curso": 2,
  "acepta_trabajo": true,
  "timestamp_unix": 1762860000
}
```

El estado efectivo lo decide el coordinador, no el nodo (ver
`app/dominio/heartbeat.py`):

| Nodo reporta | Estado para el planificador |
|---|---|
| `acepta_trabajo=false` | `CAIDO` (pausado o fuera de política) |
| `consultas_en_curso > 0` | `OCUPADO` |
| sino | `CONECTADO` |

404 si el nodo no existe (hay que re-registrarse).

### Canal WebSocket (despacho de trabajo)

`GET /ws/nodos/{nodo_id}` — solo acepta conexiones iniciadas por el nodo
(nat-friendly). Una conexión por nodo; si hay dos, la vieja se cierra.

**Coordinador → nodo** (`asignacion`):

```json
{
  "tipo": "asignacion",
  "trabajo_id": "uuid",
  "modelo_hash": "...",
  "prompt": "texto de la consulta del usuario",
  "posicion": 0,
  "cadena": ["n0", "n1"],
  "siguiente_nodo_id": "n1",
  "timeout_ms": 60000,
  "rol": "primaria"
}
```

`rol` es `"primaria"` o `"verificacion"` — ver "Verificación por réplicas"
más abajo. El nodo no decide nada con él, solo lo repite en su `resultado`.

`prompt` es el texto real de la consulta: el nodo lo ejecuta con su motor.
Si falta (contrato viejo), el nodo cae a su `--prompt-demo`.

**Nodo → coordinador** (opcional, `latido` por el mismo canal):
`{"tipo": "latido", "consultas_en_curso": 2, "acepta_trabajo": true}`

**Nodo → coordinador** (`resultado`, cierra una asignación procesada):
`{"tipo": "resultado", "trabajo_id": "...", "exito": true, "texto": "...", "error": "", "rol": "primaria", "tokens": 42}`

`tokens` es opcional (0 si falta): cuántos tokens generó el motor. El
coordinador lo usa para las métricas agregadas.

Sin verificación activa, el coordinador pasa el trabajo directo a
`COMPLETADO` (guarda `texto_resultado`) o a `FALLIDO` (guarda `error`). Un
`resultado` sobre un trabajo ya terminal se ignora (idempotente ante
reenvíos tras una reconexión). El usuario lo lee con
`GET /consultas/{trabajo_id}` (`texto_resultado` / `error`, más
`latencia_ms` y `tokens_generados` si hubo despacho).

#### Verificación por réplicas

Con `COMUNIDAD_IA_TASA_VERIFICACION` > 0 (0.0 por defecto, desactivada), una
fracción de las consultas se despacha por duplicado: dos nodos
independientes —nunca el mismo nodo para las dos copias— reciben la misma
consulta, uno con `rol: "primaria"` y otro con `rol: "verificacion"`. Esto
solo se activa si **ambas** copias se pueden despachar en el momento (hay
un segundo candidato y tiene el canal abierto); si no, la consulta sigue su
camino normal de una sola copia, sin verificación.

Mientras llega una sola de las dos respuestas, el trabajo queda
`VERIFICANDO` (no `EN_CURSO`: son estados distintos, aunque el vigilante de
timeout trata a los dos igual). Cuando llegan las dos:

- **Coinciden** (mismo éxito, mismo texto exacto) → `COMPLETADO` con ese
  texto.
- **No coinciden** — incluida la combinación "una falló y la otra no", o
  las dos fallaron con errores distintos — → `FALLIDO`, con el error
  genérico de discrepancia. No se intenta adivinar cuál de las dos es la
  correcta: una discrepancia es la señal de que algo anda mal (nodo
  deshonesto o roto), así que el diseño prefiere fallar visible.

`GET /consultas/{trabajo_id}` expone `cadena_verificacion`,
`resultado_primario` y `resultado_secundario` (cada uno `[exito, texto]` o
`null` si esa copia todavía no llegó) para poder inspeccionar una
discrepancia después de que pasó.

**Limitación conocida, a propósito:** por ahora la comparación es de texto
exacto. Un LLM real con sampling (temperatura > 0) puede dar respuestas
válidas pero distintas entre dos nodos honestos, lo que haría fallar la
verificación por una discrepancia legítima, no por un nodo malicioso. Para
un uso real hace falta temperatura 0 (greedy, determinístico) en los nodos
que participan de verificación, o una comparación más laxa (similaridad en
vez de igualdad exacta) — ninguna de las dos cosas está implementada
todavía.

Al desconectarse, el nodo se marca `CAIDO` de inmediato.

### Consulta y despacho

`POST /consultas` arma la cadena con el planificador y despacha al primer
nodo conectado. Respuesta:

```json
{
  "trabajo_id": "uuid",
  "cadena": ["nodo-a", "nodo-b"],
  "estado": "en_curso",
  "despachado": true
}
```

Si el nodo no tiene canal abierto queda `en_cola` (`despachado=false`).
`GET /consultas/{trabajo_id}` consulta el estado (`en_cola`, `en_curso`,
`verificando`, `completado`, `fallido`).

## Configuración

| Variable | Defecto | Significado |
|---|---|---|
| `COMUNIDAD_IA_BD_URL` | (vacía) | Postgres; vacía = memoria |
| `COMUNIDAD_IA_LATIDO_TIMEOUT_S` | 30 | segundos sin latido → nodo CAIDO |
| `COMUNIDAD_IA_TRABAJO_TIMEOUT_S` | 60 | segundos EN_CURSO sin resultado → FALLIDO |
| `COMUNIDAD_IA_REINTENTO_COLA_S` | 10 | cada cuánto se reintenta despachar EN_COLA |
| `COMUNIDAD_IA_TASA_VERIFICACION` | 0.0 | fracción de consultas con réplica independiente |

El vigilante de latidos corre cada `timeout/3`; el peor retraso de detección
es ~1.33×timeout. El nodo de escritorio late cada 10 s.

## Métricas (`GET /metricas`)

Endpoint de solo lectura con lo medido por el prototipo:

- `trabajos`: total, conteo por estado y `tasa_error` (fallidos sobre
  resueltos).
- `latencia_ms`: `p50`, `p95` y `muestra`, calculadas sobre trabajos
  completados que tuvieron despacho.
- `tokens`: total generado y `por_segundo` agregada (tokens sobre segundos
  observados, solo trabajos con ambos datos).
- `nodos`: total, conteo por estado, consultas en curso y
  `tokens_por_segundo_promedio`, más `detalle` por nodo con GPU y tokens/s
  reportados en el registro.

Los percentiles son de rango más cercano (`app/dominio/metricas.py`), no
interpolados: con muestras chicas devuelven un valor realmente observado.
Todavía no hay Prometheus/Grafana ni series temporales; esto es la base
medible del MVP.

## Pendiente conocido

- **Pipeline multi-nodo por capas: no implementado** y en contradicción con el
  runtime actual (cada nodo ejecuta el modelo completo). No es un pendiente
  mecánico de "reenviar activaciones": es la Ruta B de I+D descrita en
  `docs/arquitectura.md`. Hoy el resultado que vuelve es siempre final.
- Modo determinista (temperatura 0) o comparación tolerante para que la
  verificación por réplicas no marque como fallo dos respuestas honestas.
- Reputación y créditos conectados a las discrepancias.
- Cancelación/timeout local en el nodo: el coordinador puede vencer el trabajo
  mientras el nodo sigue procesando.
- Formalizar el esquema JSON con Protobuf v1 (hoy no está cableado).
