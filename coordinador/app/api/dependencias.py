"""Inyección de dependencias de FastAPI.

El estado de la aplicación (repositorios) se arma en el lifespan de
main.py: Postgres si hay COMUNIDAD_IA_BD_URL, memoria si no. Los routers
consumen los repositorios vía estas funciones de dependencia.
"""

from __future__ import annotations

from fastapi import Request

from app.infraestructura.repositorios.base import (
    RepositorioCandidatos,
    RepositorioCreditos,
    RepositorioTrabajos,
)


def repo_candidatos(request: Request) -> RepositorioCandidatos:
    return request.app.state.repositorio_candidatos


def repo_trabajos(request: Request) -> RepositorioTrabajos:
    return request.app.state.repositorio_trabajos


def repo_creditos(request: Request) -> RepositorioCreditos:
    return request.app.state.repositorio_creditos
