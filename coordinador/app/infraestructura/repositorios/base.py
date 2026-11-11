"""Protocolos (interfaces) de los repositorios.

Los endpoints y el dominio dependen de estos contratos, no de las
implementaciones concretas (principio de inversión de dependencias). Las
implementaciones son asíncronas porque la implementación Postgres hace I/O
de red: mantener una única forma invocable evita dobles declaraciones.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.dominio.creditos import TipoAsiento
from app.dominio.nodos import Candidato, EstadoNodo
from app.dominio.trabajos import Trabajo


@runtime_checkable
class RepositorioCandidatos(Protocol):
    async def registrar(self, candidato: Candidato) -> None: ...

    async def listar_por_modelo(self, modelo_hash: str) -> list[Candidato]: ...

    async def listar_todos(self) -> list[Candidato]: ...

    async def actualizar_latido(
        self,
        nodo_id: str,
        estado: EstadoNodo,
        consultas_en_curso: int,
        momento_unix: float,
    ) -> bool:
        """Persiste el estado y la carga reportados por un heartbeat.
        Devuelve False si el nodo no existe."""
        ...

    async def marcar_caidos_sin_latido(self, ahora_unix: float, timeout_s: float) -> list[str]:
        """Marca como CAIDOS los nodos cuyo último latido venció.
        Devuelve los ids afectados."""
        ...


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
