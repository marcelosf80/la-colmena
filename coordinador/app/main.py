from __future__ import annotations

from fastapi import FastAPI

from app.api import rutas_nodos, rutas_usuarios
from app.config import configuracion

app = FastAPI(title=configuracion.nombre_app)

app.include_router(rutas_nodos.router)
app.include_router(rutas_usuarios.router)


@app.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok", "entorno": configuracion.entorno}
