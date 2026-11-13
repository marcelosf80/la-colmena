from __future__ import annotations

from pydantic_settings import BaseSettings


class Configuracion(BaseSettings):
    nombre_app: str = "la-colmena-coordinador"
    entorno: str = "desarrollo"
    # URL Postgres (asyncpg), ej:
    # postgresql://usuario:clave@localhost:5432/colmena
    # Vacía => los repositorios funcionan en memoria (dev/tests).
    bd_url: str = ""
    # Segundos sin heartbeat antes de marcar un nodo como CAIDO.
    latido_timeout_s: float = 30.0
    # Segundos que un trabajo puede quedar EN_CURSO antes de marcarlo
    # FALLIDO por timeout (el nodo murió entre procesar y enviar, o nunca
    # mandó el `resultado`). Es la misma ventana que se le informa al nodo
    # como `timeout_ms` en la asignación (rutas_usuarios.py) — una sola
    # fuente de verdad para que nunca queden desincronizados.
    trabajo_timeout_s: float = 60.0

    model_config = {"env_prefix": "COMUNIDAD_IA_"}


configuracion = Configuracion()
