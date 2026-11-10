"""Entidades relacionadas a nodos y su participación en posiciones del modelo."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class EstadoNodo(Enum):
    CONECTADO = auto()
    OCUPADO = auto()
    CAIDO = auto()


@dataclass(frozen=True, slots=True)
class Nodo:
    nodo_id: str
    ram_donada_mb: int
    cores_donados: int
    tiene_gpu: bool
    tokens_por_segundo: float
    estado: EstadoNodo = EstadoNodo.CONECTADO


@dataclass(frozen=True, slots=True)
class Candidato:
    """Relación nodo↔posición: qué nodo sirve qué bloque de capas de qué modelo."""

    modelo_hash: str
    posicion: int
    nodo: Nodo
    consultas_en_curso: int = 0

    def disponible(self) -> bool:
        return self.nodo.estado == EstadoNodo.CONECTADO
