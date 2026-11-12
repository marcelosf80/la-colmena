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

Nodo → coordinador (resultado de una asignación ya procesada):
    {"tipo": "resultado", "trabajo_id": "...", "exito": true,
     "texto": "...", "error": ""}

Si el nodo se desconecta, se marca CAIDO de inmediato: el planificador deja
de asignarle trabajo hasta que vuelva a registrarse y latir.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dominio.heartbeat import Latido, estado_efectivo
from app.dominio.nodos import EstadoNodo
from app.dominio.trabajos import aplicar_resultado
from app.infraestructura.repositorios.base import RepositorioCandidatos, RepositorioTrabajos

registro = logging.getLogger("la_colmena")

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
    try:
        await repositorio.actualizar_latido(
            nodo_id=nodo_id,
            estado=EstadoNodo.CAIDO,
            consultas_en_curso=0,
            momento_unix=time.time(),
        )
    except Exception:  # noqa: BLE001 - el canal no debe morir por un error de BD
        registro.exception("no se pudo marcar CAIDO a %s tras desconección", nodo_id)


async def _procesar_resultado(repositorio_trabajos: RepositorioTrabajos, mensaje: dict) -> None:
    """Aplica un mensaje `resultado` al trabajo correspondiente.

    Separada del handler (igual que `_marcar_caido`) para poder testearla
    sin WebSocket real, y para que un mensaje malformado o un trabajo
    desconocido no tire abajo el canal completo.
    """
    trabajo_id = mensaje.get("trabajo_id")
    if not trabajo_id:
        registro.warning("mensaje 'resultado' sin trabajo_id, se ignora")
        return
    try:
        trabajo = await repositorio_trabajos.obtener(trabajo_id)
        if trabajo is None:
            registro.warning("resultado para trabajo desconocido %s, se ignora", trabajo_id)
            return
        trabajo = aplicar_resultado(
            trabajo,
            exito=bool(mensaje.get("exito", False)),
            texto=str(mensaje.get("texto", "")),
            error=str(mensaje.get("error", "")),
        )
        await repositorio_trabajos.guardar(trabajo)
    except Exception:  # noqa: BLE001 - el canal no debe morir por un error de BD
        registro.exception("no se pudo aplicar el resultado del trabajo %s", trabajo_id)


async def despedir_nodo(
    gestor: GestorConexiones,
    repositorio: RepositorioCandidatos,
    nodo_id: str,
    websocket: WebSocket,
) -> None:
    """Al perder el canal: desregistrar la conexión y marcar CAIDO al nodo
    para que el planificador deje de asignarle trabajo hasta que reconecte.
    Función separada del handler para poder testearla sin un WebSocket real.
    """
    if await gestor.desconectar(nodo_id, websocket):
        registro.info("nodo %s desconectado: marcando CAIDO", nodo_id)
        await _marcar_caido(repositorio, nodo_id)


@router.websocket("/ws/nodos/{nodo_id}")
async def canal_nodo(websocket: WebSocket, nodo_id: str) -> None:
    gestor: GestorConexiones = websocket.app.state.gestor_conexiones
    repositorio: RepositorioCandidatos = websocket.app.state.repositorio_candidatos
    repositorio_trabajos: RepositorioTrabajos = websocket.app.state.repositorio_trabajos

    await websocket.accept()
    await gestor.conectar(nodo_id, websocket)

    try:
        while True:
            mensaje = await websocket.receive_json()
            tipo = mensaje.get("tipo")

            if tipo == "resultado":
                await _procesar_resultado(repositorio_trabajos, mensaje)
                continue

            if tipo != "latido":
                continue

            latido = Latido(
                nodo_id=nodo_id,
                consultas_en_curso=int(mensaje.get("consultas_en_curso", 0)),
                acepta_trabajo=bool(mensaje.get("acepta_trabajo", True)),
                timestamp_unix=int(time.time()),
            )
            try:
                await repositorio.actualizar_latido(
                    nodo_id=nodo_id,
                    estado=estado_efectivo(latido),
                    consultas_en_curso=latido.consultas_en_curso,
                    momento_unix=float(latido.timestamp_unix),
                )
            except Exception:  # noqa: BLE001
                registro.exception("latido de %s no se pudo persistir", nodo_id)
    except WebSocketDisconnect:
        pass
    finally:
        await despedir_nodo(gestor, repositorio, nodo_id, websocket)
