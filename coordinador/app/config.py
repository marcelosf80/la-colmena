from __future__ import annotations

from pydantic_settings import BaseSettings


class Configuracion(BaseSettings):
    nombre_app: str = "la-colmena-coordinador"
    entorno: str = "desarrollo"

    model_config = {"env_prefix": "COMUNIDAD_IA_"}


configuracion = Configuracion()
