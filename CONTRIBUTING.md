# Contribuir a La Colmena

¡Gracias por tu interés! Este proyecto está en fase temprana, así que hay
mucho que construir y varias formas de ayudar: código, documentación,
pruebas, ideas de diseño e infraestructura.

## Antes de empezar

1. Abrí un **issue** describiendo qué querés hacer (bug, mejora, feature).
   Así evitamos trabajo duplicado y discutimos el diseño antes del PR.
2. Para cambios grandes (nuevo componente, cambio de protocolo) abrí un
   issue de diseño primero. El protocolo Protobuf es **v1**: cualquier
   cambio incompatible requiere v2 y un período de soporte dual.
3. Comentar en español o inglés, lo que te resulte cómodo.

## Cómo levantar el entorno

### Coordinador (Python 3.11+)

```bash
cd coordinador
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest tests/unitarios -v        # los 75 tests deben pasar
uvicorn app.main:app --reload    # http://localhost:8000
```

### Nodo de escritorio (Rust)

```bash
cd nodo-escritorio
cargo test                       # los 39 tests deben pasar
cargo build --release
```

> `Cargo.toml` usa rangos de versión y `Cargo.lock` está versionado: el CI
> corre `cargo test --locked` con Rust estable. Si actualizás dependencias,
> regenerá el lock con `cargo update` y verificá que los tests pasen.

### Docker

```bash
cd infraestructura
docker compose up --build
```

## Reglas del repositorio

- **Cada PR pasa CI**: los 33 tests deben seguir pasando.
- **Tests primero para lógica de dominio.** El planificador, los créditos y
  las políticas de recursos son funciones puras: cubrí cada regla nueva con
  un test unitario.
- **El dominio no importa FastAPI ni I/O.** Arquitectura hexagonal: la
  lógica vive en `app/dominio/`, la red en `app/api/`, la persistencia en
  `app/infraestructura/`. Los endpoints son `async` y los repositorios se
  inyectan con `Depends` (ver [`docs/persistencia.md`](docs/persistencia.md)).
- **Sin credenciales ni datos reales** en el código. Usá `.env` (gitignored).
- **Commits en español, pequeños y descriptivos.**

English is welcome for code comments if you prefer — consistency within a
file matters most.

## Áreas donde se necesita ayuda

| Área | Tipo de tarea |
|---|---|
| `coordinador/app/infraestructura` | Migraciones versionadas (alembic) |
| `nodo-escritorio/src/ejecutor_modelo.rs` | Benchmark real de tokens/s al conectar |
| `nodo-escritorio` | Cancelación/timeout local, modo determinista (temperatura 0) para verificación |
| `docs/` | ADRs, decisiones abiertas (descentralización del coordinador) |
| `infraestructura/` | Métricas, healthchecks (Prometheus/Grafana) |
| CI | Cobertura de tests, linting (ruff/clippy) |

## Estilo

- Python: `ruff` + `mypy` cuando se agreguen; seguir el estilo existente
  (type hints completos, docstrings en español).
- Rust: `rustfmt` y `clippy` sin warnings.
- SVG/diagramas: se aceptan PRs mejorando `docs/img/` para el banner.

## Reportar bugs

Abrí un issue en `.github/ISSUE_TEMPLATE/bug_report.md` con pasos para
reproducir, salida completa del error y versión del entorno.
