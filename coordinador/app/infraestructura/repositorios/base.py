"""Protocolos (interfaces) de los repositorios.

Los endpoints y el dominio dependen de estos contratos, no de las
implementaciones concretas (principio de inversión de dependencias). Las
implementaciones son asíncronas porque la implementación Postgres hace I/O
de red: mantener una única forma invocable evita dobles declaraciones.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.dominio.creditos import TipoAsiento
from app.dominio.nodos import Candidato
from app.dominio.trabajos import Trabajo


@runtime_checkable
class RepositorioCandidatos(Protocol):
    async def registrar(self, candidato: Candidato) -> None: ...

    async def listar_por_modelo(self, modelo_hash: str) -> list[Candidato]: ...

    async def listar_todos(self) -> list[Candidato]: ...


@runtime_checkable
class RepositorioTrabajos(Protocol):
    async def guardar(self, trabajo: Trabajo) -> None: ...

    async def obtener(self, trabajo_id: str) -> Trabajo | None: ...


@runtime_checkable
class RepositorioCreditos(Protocol):
    async def registrar_asiento(
        self, cuenta_id: str, tipo: TipoAsiento, monto: float
    ) -> None: ...

    async def saldos(self, cuenta_id: str) -> tuple[float, float]:
        """Devuelve (aportes, consumos) acumulados de la cuenta."""
        ...
