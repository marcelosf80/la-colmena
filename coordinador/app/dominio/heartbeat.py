"""Lógica pura de heartbeat: estado efectivo de un nodo y detección de caídos.

Separada del transporte (HTTP/WebSocket) para poder testearla sin red, igual
que el planificador.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.dominio.nodos import EstadoNodo


@dataclass(frozen=True, slots=True)
class Latido:
    """Reporte periódico de un nodo al coordinador (espejo de Heartbeat en
    `packages/protocolo/esquemas/mensajes.proto`)."""

    nodo_id: str
    consultas_en_curso: int
    acepta_trabajo: bool = True
    timestamp_unix: int = 0


def estado_efectivo(latido: Latido) -> EstadoNodo:
    """El estado lo decide la carga real, no lo que el nodo "dice" ser:
    si no acepta trabajo (pausado por el usuario o fuera de política de
    recursos) queda CAIDO para el planificador; si tiene consultas en curso
    está OCUPADO; si no, CONECTADO.
    """
    if not latido.acepta_trabajo:
        return EstadoNodo.CAIDO
    if latido.consultas_en_curso > 0:
        return EstadoNodo.OCUPADO
    return EstadoNodo.CONECTADO


def nodos_sin_latido(
    ultimos_latidos_unix: dict[str, float], ahora_unix: float, timeout_s: float
) -> list[str]:
    """Nodos cuyo último heartbeat supera el timeout. El coordinador los
    marca CAIDOS para que el planificador deje de asignarles trabajo."""
    return [
        nodo_id
        for nodo_id, momento in ultimos_latidos_unix.items()
        if ahora_unix - momento > timeout_s
    ]
