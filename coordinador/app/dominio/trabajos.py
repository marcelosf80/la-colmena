"""Entidad Trabajo: una consulta de un usuario y la cadena de nodos que la atiende."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class EstadoTrabajo(Enum):
    EN_COLA = auto()
    EN_CURSO = auto()
    COMPLETADO = auto()
    FALLIDO = auto()


@dataclass(slots=True)
class Trabajo:
    trabajo_id: str
    modelo_hash: str
    usuario_id: str
    cadena_nodo_ids: list[str] = field(default_factory=list)
    estado: EstadoTrabajo = EstadoTrabajo.EN_COLA
