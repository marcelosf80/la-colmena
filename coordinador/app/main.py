from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api import rutas_nodos, rutas_usuarios, websockets
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

registro = logging.getLogger("la_colmena")


async def _vigilar_latidos(app: FastAPI) -> None:
    """Marca CAIDOS los nodos que dejaron de latir.

    Corre cada timeout/3 para que la detección tenga a lo sumo ~1.3×timeout
    de retraso sin generar carga apreciable.
    """
    intervalo = max(1.0, configuracion.latido_timeout_s / 3)
    while True:
        await asyncio.sleep(intervalo)
        try:
            caidos = await app.state.repositorio_candidatos.marcar_caidos_sin_latido(
                ahora_unix=time.time(),
                timeout_s=configuracion.latido_timeout_s,
            )
            for nodo_id in caidos:
                registro.warning("nodo %s sin heartbeat: marcado CAIDO", nodo_id)
        except Exception:  # noqa: BLE001 - el vigilante no debe morir por un error de BD
            registro.exception("fallo el vigilante de heartbeats")


async def _vigilar_trabajos_vencidos(app: FastAPI) -> None:
    """Marca FALLIDO los trabajos EN_CURSO que se pasaron del timeout.

    Cubre el caso en que el nodo asignado muere (o pierde el canal) entre
    procesar la consulta y mandar el `resultado`: sin este vigilante, ese
    trabajo quedaría EN_CURSO para siempre y el usuario nunca sabría que
    no va a llegar respuesta.
    """
    intervalo = max(1.0, configuracion.trabajo_timeout_s / 3)
    while True:
        await asyncio.sleep(intervalo)
        try:
            vencidos = await app.state.repositorio_trabajos.marcar_vencidos(
                ahora_unix=time.time(),
                timeout_s=configuracion.trabajo_timeout_s,
            )
            for trabajo_id in vencidos:
                registro.warning("trabajo %s sin resultado a tiempo: marcado FALLIDO", trabajo_id)
        except Exception:  # noqa: BLE001 - el vigilante no debe morir por un error de BD
            registro.exception("fallo el vigilante de trabajos vencidos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arma repositorios y conexiones: Postgres si COMUNIDAD_IA_BD_URL está
    definida, memoria si no (dev y tests). Arranca el vigilante de
    heartbeats y cierra todo al apagar.
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

    app.state.gestor_conexiones = websockets.GestorConexiones()
    vigilante_latidos = asyncio.create_task(_vigilar_latidos(app))
    vigilante_trabajos = asyncio.create_task(_vigilar_trabajos_vencidos(app))

    yield

    for vigilante in (vigilante_latidos, vigilante_trabajos):
        vigilante.cancel()
        with suppress(asyncio.CancelledError):
            await vigilante
    if pool is not None:
        await pool.close()


app = FastAPI(title=configuracion.nombre_app, lifespan=lifespan)

app.include_router(rutas_nodos.router)
app.include_router(rutas_usuarios.router)
app.include_router(websockets.router)


@app.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok", "entorno": configuracion.entorno}
