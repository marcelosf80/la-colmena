from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import rutas_nodos, rutas_usuarios
from app.config import configuracion
from app.infraestructura.repositorios.candidatos import (
    RepositorioCandidatosEnMemoria,
    RepositorioCreditosEnMemoria,
    RepositorioTrabajosEnMemoria,
)
from app.infraestructura.repositorios.postgres import (
    RepositorioCandidatosPostgres,
    RepositorioCreditosPostgres,
    RepositorioTrabajosPostgres,
    armar_pool,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arma los repositorios: Postgres si COMUNIDAD_IA_BD_URL está definida,
    memoria si no (dev y tests). Cierra el pool al apagar.
    """
    if configuracion.bd_url:
        pool = await armar_pool(configuracion.bd_url)
        app.state.repositorio_candidatos = RepositorioCandidatosPostgres(pool)
        app.state.repositorio_trabajos = RepositorioTrabajosPostgres(pool)
        app.state.repositorio_creditos = RepositorioCreditosPostgres(pool)
        app.state.pool_bd = pool
    else:
        pool = None
        app.state.repositorio_candidatos = RepositorioCandidatosEnMemoria()
        app.state.repositorio_trabajos = RepositorioTrabajosEnMemoria()
        app.state.repositorio_creditos = RepositorioCreditosEnMemoria()

    yield

    if pool is not None:
        await pool.close()


app = FastAPI(title=configuracion.nombre_app, lifespan=lifespan)

app.include_router(rutas_nodos.router)
app.include_router(rutas_usuarios.router)


@app.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok", "entorno": configuracion.entorno}
