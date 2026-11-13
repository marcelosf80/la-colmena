"""Entidad Trabajo: una consulta de un usuario y la cadena de nodos que la atiende.

`aplicar_resultado` queda separada de la entidad y del transporte (igual que
`estado_efectivo` en heartbeat.py) para poder testear la transición de
estado sin WebSocket ni repositorio.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    texto_resultado: str | None = None
    error: str | None = None


def aplicar_resultado(trabajo: Trabajo, exito: bool, texto: str, error: str) -> Trabajo:
    """Devuelve una copia del trabajo con el resultado que reportó el nodo.

    No se aplica si el trabajo ya estaba en un estado terminal: el nodo
    puede reenviar un `resultado` (por ejemplo tras una reconexión) y no
    queremos que un mensaje tardío pise un resultado ya asentado.
    """
    if trabajo.estado in (EstadoTrabajo.COMPLETADO, EstadoTrabajo.FALLIDO):
        return trabajo
    if exito:
        return replace(trabajo, estado=EstadoTrabajo.COMPLETADO, texto_resultado=texto, error=None)
    return replace(trabajo, estado=EstadoTrabajo.FALLIDO, texto_resultado=None, error=error)


MENSAJE_TIMEOUT = "timeout: el nodo no devolvió resultado a tiempo"


def marcar_vencido(trabajo: Trabajo) -> Trabajo:
    """Si el trabajo quedó EN_CURSO más tiempo del permitido (el nodo se
    cayó, o nunca mandó el `resultado`), lo marca FALLIDO.

    Solo actúa sobre EN_CURSO a propósito: un trabajo EN_COLA (nunca se
    pudo despachar porque el nodo no estaba conectado) es un problema
    distinto — de cola/reintento, no de timeout — y uno ya en estado
    terminal no se toca, igual que en `aplicar_resultado`.
    """
    if trabajo.estado is not EstadoTrabajo.EN_CURSO:
        return trabajo
    return replace(trabajo, estado=EstadoTrabajo.FALLIDO, texto_resultado=None, error=MENSAJE_TIMEOUT)
