from __future__ import annotations

from pydantic_settings import BaseSettings


class Configuracion(BaseSettings):
    nombre_app: str = "la-colmena-coordinador"
    entorno: str = "desarrollo"
    # URL Postgres (asyncpg), ej:
    # postgresql://usuario:clave@localhost:5432/colmena
    # Vacía => los repositorios funcionan en memoria (dev/tests).
    bd_url: str = ""

    model_config = {"env_prefix": "COMUNIDAD_IA_"}


configuracion = Configuracion()
