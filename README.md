<p align="center">
  <img src="docs/img/banner.svg" alt="La Colmena" width="100%">
</p>

# 🐝 La Colmena

**Red P2P de cómputo compartido para IA.** Los usuarios donan recursos de su
máquina (CPU, GPU, RAM) para ejecutar modelos de código abierto en conjunto,
como abejas aportando a una colmena.

> No se comparten archivos de modelos entre pares: cada nodo descarga los
> pesos desde el catálogo oficial. **Lo que se comparte es cómputo.**

<p align="center">
  <img src="docs/img/arquitectura.svg" alt="Diagrama de arquitectura" width="90%">
</p>

## Badges

![Estado](https://img.shields.io/badge/estado-MVP%20multi--nodo-FFB300)
![Tests](https://img.shields.io/badge/tests-90%20%2B%2045%20nodo%20%2B%20integracion-4CAF50)
![Lenguajes](https://img.shields.io/badge/Python-FastAPI-3776AB?logo=python&logoColor=white)
![Rust](https://img.shields.io/badge/Rust-daemon%20nodo-DEA584?logo=rust&logoColor=black)
![Protocolo](https://img.shields.io/badge/protocolo-Protobuf%20v1-A2AAFF)
![Contribs welcome](https://img.shields.io/badge/contribuciones-bienvenidas-FFB300)
![Licencia](https://img.shields.io/badge/licencia-MIT-9FA8DA)

## Cómo funciona hoy

El MVP es una **red de réplicas de modelos completos**: cada nodo descarga y
ejecuta el mismo modelo con `llama-server`, y el coordinador reparte las
consultas entre los nodos disponibles.

```text
Usuario ──► Coordinador ──► [Nodo A: modelo completo] ──► respuesta
                         └─► [Nodo B: modelo completo]  (réplica / verificación)
```

- **La capacidad total escala con la cantidad de nodos.** Una consulta la
  atiende un nodo (o dos, si la verificación está activa), no una cadena de
  capas.
- **Réplicas independientes** permiten seguir respondiendo si un nodo se cae y
  comparar resultados cuando la verificación está habilitada.
- **Créditos desde dos lados**: donar cómputo genera aportes, consumir genera
  consumos; el ratio define prioridad de cola.
- **Lo que todavía no hace**: no particiona un modelo entre máquinas ni suma
  VRAM/RAM entre equipos. El particionado real por capas es una línea de I+D
  separada, documentada en [`docs/arquitectura.md`](docs/arquitectura.md).

## Componentes

| Componente | Stack | Rol | Estado |
|---|---|---|---|
| [`coordinador/`](coordinador/) | Python 3.11 · FastAPI | Registra nodos, planifica, lleva créditos, despacha por WS y gestiona el ciclo de vida de los trabajos | ✅ 90 tests |
| [`nodo-escritorio/`](nodo-escritorio/) | Rust | Daemon del usuario: registro, heartbeat, políticas de recursos, inferencia real y resultados por WS | ✅ 45 tests |
| [`packages/protocolo/`](packages/protocolo/) | Protobuf v1 | Contrato compartido por todas las implementaciones | 📝 esquema definido, aún no cableado |
| [`infraestructura/`](infraestructura/) | docker-compose | Coordinador + Postgres 17 | ✅ Postgres conectado |
| Nodo Android | Kotlin | Mismo rol del nodo de escritorio, con restricciones de batería/red | 🚫 fuera del MVP |

## Arquitectura del coordinador

Modelo de dominio documentado en [`docs/arquitectura.md`](docs/arquitectura.md).
Decisiones destacadas:

- **Planificador como función pura** sin I/O: dado el estado de candidatos, elige la réplica menos cargada para cada posición (slot lógico del modelo, no un rango de capas). Testeable sin base de datos ni red.
- **Detección de puntos únicos de falla**: posiciones con un solo candidato disponible se priorizan al asignar nodos nuevos.
- **Arquitectura hexagonal**: dominio limpio, repositorios intercambiables. Hoy hay dos implementaciones: **en memoria** (dev/tests) y **Postgres** (producción), con la misma interfaz async. Ver [`docs/persistencia.md`](docs/persistencia.md).

## Probarlo en tu PC (o en varias)

Para levantar el coordinador y un nodo sin acordarte de todos los
comandos, hay scripts listos en [`scripts/`](scripts/):

```powershell
# Windows (PowerShell)
.\scripts\iniciar-coordinador.ps1
.\scripts\iniciar-nodo.ps1 -Coordinador "http://localhost:8000" -ModeloHash "prueba-1"
```

```bash
# Linux/Mac
./scripts/iniciar-coordinador.sh
MODELO_HASH=prueba-1 ./scripts/iniciar-nodo.sh
```

Para la prueba real con dos o más PCs en la misma red (conseguir
`llama-server`, un modelo `.gguf`, firewall de Windows, verificación por
réplicas entre máquinas distintas), seguí
[`docs/prueba-real.md`](docs/prueba-real.md).

## Ejemplos

**Correr el coordinador y registrar un nodo:**

```bash
# 1. Coordinador
cd coordinador
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 2. Nodo de escritorio (terminal aparte)
cd nodo-escritorio
cargo build --release
./target/release/nodo-escritorio \
  --coordinador http://localhost:8000 \
  --nodo-id mi-nodo-1 \
  --modelo-hash <hash-del-modelo> \
  --posicion 0 \
  --ram-max-mb 4096 \
  --cpu-max-pct 50 \
  --llama-server ./llama-server \
  --pesos ./modelos/<modelo>.gguf

# Sin --llama-server y --pesos, el nodo usa el motor simulado (dev/CI).
# 3. Verificar que apareció en la red
curl http://localhost:8000/nodos/<hash-del-modelo>
```

El nodo **late cada 10 segundos** al coordinador (HTTP) y **recibe
asignaciones por WebSocket**; al terminar, **devuelve el resultado por el
mismo canal**. Si abrís una consulta mientras el nodo está corriendo, verás el
ciclo completo en el log del daemon. Ver
[`docs/heartbeat-y-canal.md`](docs/heartbeat-y-canal.md).

> **Nota:** la asignación transporta el prompt real de la consulta. Si el
> coordinador no lo manda (contrato viejo), el nodo usa `--prompt-demo` como
> respaldo para no quedar sin nada que ejecutar.

**Métricas del prototipo:**

```bash
curl http://localhost:8000/metricas
```

Devuelve trabajos por estado, tasa de error, latencia p50/p95, tokens
generados y la tasa agregada, más el detalle de cada nodo (estado, GPU,
tokens/s medidos y consultas en curso). Es la base reproducible que pide el
informe; todavía no reemplaza Prometheus/Grafana.

**Con Docker (coordinador + Postgres):**

```bash
cd infraestructura
docker compose up --build
```

**Tests:**

```bash
cd coordinador && pytest tests/unitarios -v   # 90 tests
cd nodo-escritorio && cargo test              # 45 tests
```

**Con Postgres local:**

```bash
export COMUNIDAD_IA_BD_URL="postgresql://comunidad_ia:cambiar_en_produccion@localhost:5432/comunidad_ia"
uvicorn app.main:app --reload   # desde coordinador/
```

## Hoja de ruta

**MVP actual — réplicas de modelos completos (Ruta A):**

- [x] Esquema Protobuf del protocolo (definido; el transporte real sigue en JSON)
- [x] Coordinador: dominio + API base (nodos, usuarios, créditos, planificador)
- [x] Persistencia Postgres (repositorios async, esquema idempotente, CI con base real)
- [x] Heartbeat real + WebSocket para despachar trabajo
- [x] Nodo de escritorio: registro, heartbeat real, políticas de recursos, control de usuario
- [x] Inferencia real con llama.cpp (binario oficial `llama-server`, sin FFI ni toolchain C++)
- [x] Resultado del nodo de vuelta al coordinador por WebSocket
- [x] Prompt real de la consulta transportado al nodo en la asignación
- [x] Métricas reales: GPU detectada, benchmark de tokens/s al arrancar, latencia y tokens por trabajo (`GET /metricas`)
- [x] Timeout de trabajos `EN_CURSO` + reintento de cola `EN_COLA`
- [x] Verificación por réplicas (dos cadenas independientes; apagada por defecto)
- [ ] Modo determinista (temperatura 0) o comparación tolerante para verificación
- [ ] Detección de GPU AMD/Intel (hoy solo NVIDIA vía `nvidia-smi`) y VRAM reportada
- [ ] Reputación y créditos conectados a la verificación
- [ ] Prueba real con 2–3 PCs y modelos completos

**Fuera del MVP (no competir con lo anterior):**

- [ ] Nodo Android (Kotlin)
- [ ] Descentralización del coordinador ([discusión abierta](docs/arquitectura.md))
- [ ] I+D: inferencia particionada por capas (Ruta B, requiere otro runtime)

## Contribuir

¡Ideas, avisos de bugs, PRs y documentación son bienvenidos! Leé
[`CONTRIBUTING.md`](CONTRIBUTING.md) antes de abrir tu primer PR.

## Licencia

[MIT](LICENSE) · © 2026 La Colmena
