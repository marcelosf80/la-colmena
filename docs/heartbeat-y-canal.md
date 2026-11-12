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
  "posicion": 0,
  "cadena": ["n0", "n1"],
  "siguiente_nodo_id": "n1",
  "timeout_ms": 60000
}
```

**Nodo → coordinador** (opcional, `latido` por el mismo canal):
`{"tipo": "latido", "consultas_en_curso": 2, "acepta_trabajo": true}`

**Nodo → coordinador** (`resultado`, cierra una asignación procesada):
`{"tipo": "resultado", "trabajo_id": "...", "exito": true, "texto": "...", "error": ""}`

El coordinador pasa el trabajo a `COMPLETADO` (guarda `texto_resultado`) o a
`FALLIDO` (guarda `error`). Un `resultado` sobre un trabajo ya terminal se
ignora (idempotente ante reenvíos tras una reconexión). El usuario lo lee con
`GET /consultas/{trabajo_id}` (`texto_resultado` / `error`).

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
`completado`, `fallido`).

## Configuración

| Variable | Defecto | Significado |
|---|---|---|
| `COMUNIDAD_IA_BD_URL` | (vacía) | Postgres; vacía = memoria |
| `COMUNIDAD_IA_LATIDO_TIMEOUT_S` | 30 | segundos sin latido → nodo CAIDO |

El vigilante corre cada `timeout/3`; el peor retraso de detección es
~1.33×timeout. El nodo de escritorio lattea cada 10 s.

## Pendiente (Fase 1)

- Pipeline multi-nodo real: hoy el resultado de vuelta es siempre "final"
  y cada nodo procesa el prompt por su cuenta; falta reenviar la activación
  a `siguiente_nodo_id` y que solo el último eslabón reporte `resultado`
  (`ResultadoParcial` sigue sin implementarse).
- Cola de trabajos `EN_COLA` con reintento automático de despacho.
- Formalizar el esquema JSON con Protobuf v1.
