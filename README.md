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

![Estado](https://img.shields.io/badge/estado-fase%200%20%2B%20esqueleto%20fase%201-FFB300)
![Tests](https://img.shields.io/badge/tests-40%20pasando-4CAF50)
![Lenguajes](https://img.shields.io/badge/Python-FastAPI-3776AB?logo=python&logoColor=white)
![Rust](https://img.shields.io/badge/Rust-daemon%20nodo-DEA584?logo=rust&logoColor=black)
![Protocolo](https://img.shields.io/badge/protocolo-Protobuf%20v1-A2AAFF)
![Contribs welcome](https://img.shields.io/badge/contribuciones-bienvenidas-FFB300)
![Licencia](https://img.shields.io/badge/licencia-MIT-9FA8DA)

## La idea en una frase

En lugar de que una corporación corra el modelo en su datacenter, **una
comunidad** reparte el modelo en bloques de capas entre sus propias
computadoras y lo sirve de forma cooperativa:

```text
Usuario ──► Coordinador ──► [Nodo 0] ──► [Nodo 1] ──► [Nodo 2] ──► respuesta
             arma la cadena   capas 0-11  capas 12-23  capas 24-31
```

- **Throughput escala con la cantidad de nodos.** La latencia de una consulta individual no baja agregando nodos a la misma cadena: lo que crece es la capacidad total de la red.
- **Réplicas por posición** evitan que un nodo caído rompa el modelo.
- **Créditos desde dos lados**: donar cómputo genera aportes, consumir genera consumos; el ratio define prioridad de cola.

## Componentes

| Componente | Stack | Rol | Estado |
|---|---|---|---|
| [`coordinador/`](coordinador/) | Python 3.11 · FastAPI | Registra nodos, arma cadenas, lleva créditos | ✅ 19 tests |
| [`nodo-escritorio/`](nodo-escritorio/) | Rust | Daemon del usuario: heartbeat, políticas de recursos, motor de inferencia | ✅ 21 tests (motor = stub) |
| [`packages/protocolo/`](packages/protocolo/) | Protobuf v1 | Contrato compartido por todas las implementaciones | ✅ |
| [`infraestructura/`](infraestructura/) | docker-compose | Coordinador + Postgres 17 + Redis 7 | ✅ Postgres conectado |
| Nodo Android | Kotlin | Mismo rol del nodo de escritorio, con restricciones de batería/red | 🔜 pendiente |

## Arquitectura del coordinador

Modelo de dominio documentado en [`docs/arquitectura.md`](docs/arquitectura.md).
Decisiones destacadas:

- **Planificador como función pura** sin I/O: dado el estado de candidatos, arma la cadena eligiendo el nodo menos cargado por posición. Testeable sin base de datos ni red.
- **Detección de puntos únicos de falla**: posiciones con un solo candidato disponible se priorizan al asignar nodos nuevos.
- **Arquitectura hexagonal**: dominio limpio, repositorios intercambiables. Hoy hay dos implementaciones: **en memoria** (dev/tests) y **Postgres** (producción), con la misma interfaz async. Ver [`docs/persistencia.md`](docs/persistencia.md).

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
  --cpu-max-pct 50

# 3. Verificar que apareció en la red
curl http://localhost:8000/nodos/<hash-del-modelo>
```

**Con Docker (coordinador + Postgres + Redis):**

```bash
cd infraestructura
docker compose up --build
```

**Tests:**

```bash
cd coordinador && pytest tests/unitarios -v   # 19 tests
cd nodo-escritorio && cargo test              # 21 tests
```

**Con Postgres local:**

```bash
export COMUNIDAD_IA_BD_URL="postgresql://comunidad_ia:cambiar_en_produccion@localhost:5432/comunidad_ia"
uvicorn app.main:app --reload   # desde coordinador/
```

## Hoja de ruta

- [x] Esquema Protobuf del protocolo
- [x] Coordinador: dominio + API base (nodos, usuarios, créditos, planificador)
- [x] Persistencia Postgres (repositorios async, esquema idempotente, CI con base real)
- [x] Nodo de escritorio: registro, heartbeat local, políticas de recursos, control de usuario
- [ ] Bind real de `llama.cpp` en el nodo (hoy `MotorSimulado`)
- [ ] Heartbeat real + WebSocket para despachar trabajo
- [ ] Verificación de aportes por réplicas
- [ ] Nodo Android (Kotlin)
- [ ] Descentralización del coordinador ([discusión abierta](docs/arquitectura.md))

## Contribuir

¡Ideas, avisos de bugs, PRs y documentación son bienvenidos! Leé
[`CONTRIBUTING.md`](CONTRIBUTING.md) antes de abrir tu primer PR.

## Licencia

[MIT](LICENSE) · © 2026 La Colmena
