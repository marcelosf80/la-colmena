"""Canal de despacho de trabajo: WebSocket nodo↔coordinador.

El nodo siempre inicia la conexión (nunca expone puertos), igual que en el
registro HTTP. El coordinador guarda una conexión por nodo y le empuja las
asignaciones de trabajo.

Formato de mensajes (JSON; el esquema Protobuf v1 formalizará esto cuando
el transporte deje de ser experimental):

Coordinador → nodo:
    {"tipo": "asignacion", "trabajo_id": "...", "modelo_hash": "...",
     "posicion": 0, "cadena": ["n0", "n1"], "siguiente_nodo_id": "n1",
     "timeout_ms": 60000}

Nodo → coordinador (opcional, heartbeat por el mismo canal):
    {"tipo": "latido", "consultas_en_curso": 2, "acepta_trabajo": true}

Si el nodo se desconecta, se marca CAIDO de inmediato: el planificador deja
de asignarle trabajo hasta que vuelva a registrarse y latir.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dominio.heartbeat import Latido, estado_efectivo
from app.dominio.nodos import EstadoNodo
from app.infraestructura.repositorios.base import RepositorioCandidatos

router = APIRouter()


class GestorConexiones:
    """Registro en memoria de las conexiones WebSocket activas.

    Vive en `app.state`; no se persiste porque una conexión no sobrevive a
    un reinicio del proceso (el nodo reconecta solo).
    """

    def __init__(self) -> None:
        self._conexiones: dict[str, WebSocket] = {}

    async def conectar(self, nodo_id: str, websocket: WebSocket) -> None:
        anterior = self._conexiones.get(nodo_id)
        if anterior is not None and anterior is not websocket:
            # Un nodo no debe tener dos canales: cerramos el viejo para que
            # no queden asignaciones duplicadas.
            try:
                await anterior.close(code=1000)
            except RuntimeError:
                pass
        self._conexiones[nodo_id] = websocket

    async def desconectar(self, nodo_id: str, websocket: WebSocket) -> bool:
        """Desconecta solo si la conexión registrada es la misma (evita que
        una conexión vieja cierre el registro de la nueva)."""
        if self._conexiones.get(nodo_id) is websocket:
            del self._conexiones[nodo_id]
            return True
        return False

    async def enviar(self, nodo_id: str, mensaje: dict) -> bool:
        websocket = self._conexiones.get(nodo_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(mensaje)
            return True
        except (RuntimeError, WebSocketDisconnect):
            self._conexiones.pop(nodo_id, None)
            return False

    def conectados(self) -> list[str]:
        return list(self._conexiones)


async def _marcar_caido(repositorio: RepositorioCandidatos, nodo_id: str) -> None:
    await repositorio.actualizar_latido(
        nodo_id=nodo_id,
        estado=EstadoNodo.CAIDO,
        consultas_en_curso=0,
        momento_unix=time.time(),
    )


@router.websocket("/ws/nodos/{nodo_id}")
async def canal_nodo(websocket: WebSocket, nodo_id: str) -> None:
    gestor: GestorConexiones = websocket.app.state.gestor_conexiones
    repositorio: RepositorioCandidatos = websocket.app.state.repositorio_candidatos

    await websocket.accept()
    await gestor.conectar(nodo_id, websocket)

    try:
        while True:
            mensaje = await websocket.receive_json()
            if mensaje.get("tipo") != "latido":
                continue
            latido = Latido(
                nodo_id=nodo_id,
                consultas_en_curso=int(mensaje.get("consultas_en_curso", 0)),
                acepta_trabajo=bool(mensaje.get("acepta_trabajo", True)),
                timestamp_unix=int(time.time()),
            )
            await repositorio.actualizar_latido(
                nodo_id=nodo_id,
                estado=estado_efectivo(latido),
                consultas_en_curso=latido.consultas_en_curso,
                momento_unix=float(latido.timestamp_unix),
            )
    except WebSocketDisconnect:
        pass
    finally:
        if await gestor.desconectar(nodo_id, websocket):
            await _marcar_caido(repositorio, nodo_id)
