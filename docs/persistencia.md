# Persistencia

El coordinador guarda todo en memoria si no se configura base de datos
(útil para desarrollo y tests). Definí `COMUNIDAD_IA_BD_URL` con una URL
de Postgres y los repositorios pasan a persistir automáticamente.

```bash
export COMUNIDAD_IA_BD_URL="postgresql://comunidad_ia:cambiar_en_produccion@localhost:5432/comunidad_ia"
uvicorn app.main:app --reload
```

## Diseño

- **Interfaces** en `app/infraestructura/repositorios/base.py` (Protocols):
  `RepositorioCandidatos`, `RepositorioTrabajos`, `RepositorioCreditos`.
- **Implementación en memoria** (`candidatos.py`): referencia, tests y modo sin BD.
- **Implementación Postgres** (`postgres.py`): `asyncpg` con pool de conexiones.
- **Inyección**: el lifespan de `app/main.py` arma los repositorios según
  `COMUNIDAD_IA_BD_URL` y los expone en `app.state`; los routers los reciben
  con `Depends` (`app/api/dependencias.py`).
- Los endpoints son `async` porque el I/O de Postgres es asíncrono.

## Esquema

| Tabla | Rol |
|---|---|
| `nodos` | Identidad y recursos donados por nodo (upsert por `nodo_id`) |
| `candidatos` | Relación nodo↔modelo↔posición, con `consultas_en_curso` |
| `asientos_creditos` | Libro mayor **append-only** de aportes/consumos |
| `trabajos` | Consultas de usuarios con la cadena de nodos asignada |

El esquema se crea de forma idempotente (`CREATE TABLE IF NOT EXISTS`) al
arrancar el coordinador. Cuando el modelo de datos se estabilice, se
migrará a migraciones versionadas (alembic).

## Tests

- `tests/unitarios` no necesita base de datos (dominio + repos en memoria + API).
- `tests/integraciones/test_postgres.py` se saltea si `COMUNIDAD_IA_BD_URL`
  no está definida. En CI corre contra un servicio `postgres:17` real.

```bash
# contra Postgres local
COMUNIDAD_IA_BD_URL=postgresql://... pytest tests/integraciones -v
```
