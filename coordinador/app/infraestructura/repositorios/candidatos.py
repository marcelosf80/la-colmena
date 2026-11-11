"""Repositorios en memoria.

Implementación de referencia: sin I/O, suficiente para desarrollo local,
tests y modo sin base de datos. La interfaz es async para que endpoints y
tests no cambien al reemplazarlos por Postgres.
"""

from __future__ import annotations

from app.dominio.creditos import TipoAsiento
from app.dominio.nodos import Candidato
from app.dominio.trabajos import Trabajo


class RepositorioCandidatosEnMemoria:
    def __init__(self) -> None:
        self._candidatos: dict[str, Candidato] = {}

    async def registrar(self, candidato: Candidato) -> None:
        self._candidatos[candidato.nodo.nodo_id] = candidato

    async def listar_por_modelo(self, modelo_hash: str) -> list[Candidato]:
        return [c for c in self._candidatos.values() if c.modelo_hash == modelo_hash]

    async def listar_todos(self) -> list[Candidato]:
        return list(self._candidatos.values())


class RepositorioTrabajosEnMemoria:
    def __init__(self) -> None:
        self._trabajos: dict[str, Trabajo] = {}

    async def guardar(self, trabajo: Trabajo) -> None:
        self._trabajos[trabajo.trabajo_id] = trabajo

    async def obtener(self, trabajo_id: str) -> Trabajo | None:
        return self._trabajos.get(trabajo_id)


class RepositorioCreditosEnMemoria:
    def __init__(self) -> None:
        self._aportes: dict[str, float] = {}
        self._consumos: dict[str, float] = {}

    async def registrar_asiento(
        self, cuenta_id: str, tipo: TipoAsiento, monto: float
    ) -> None:
        if monto <= 0:
            raise ValueError("El monto de un asiento debe ser positivo")
        diccionario = self._aportes if tipo is TipoAsiento.APORTE else self._consumos
        diccionario[cuenta_id] = diccionario.get(cuenta_id, 0.0) + monto

    async def saldos(self, cuenta_id: str) -> tuple[float, float]:
        return self._aportes.get(cuenta_id, 0.0), self._consumos.get(cuenta_id, 0.0)
