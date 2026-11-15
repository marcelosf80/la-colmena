"""Tests de `reintentar_cola` aislados de FastAPI/TestClient a propósito.

`reintentar_cola` solo necesita `app.state.{repositorio_trabajos,
repositorio_candidatos, gestor_conexiones}` — armamos esos tres objetos
directamente (un `SimpleNamespace` hace de `app`) para no depender de un
WebSocket real ni de que el test corra en el mismo loop que un TestClient.
Eso evita mezclar el loop de `asyncio.run()` con el loop interno que usa
`TestClient` para sus conexiones WebSocket, que es frágil y puede colgarse.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.rutas_usuarios import reintentar_cola
from app.api.websockets import GestorConexiones
from app.dominio.nodos import Candidato, EstadoNodo, Nodo
from app.dominio.trabajos import EstadoTrabajo, Trabajo
from app.infraestructura.repositorios.candidatos import (
    RepositorioCandidatosEnMemoria,
    RepositorioTrabajosEnMemoria,
)


class WebSocketFalso:
    """Registra los mensajes recibidos, para poder verificar el contenido
    de la asignación (a diferencia del `WebSocketFalso` de
    test_websockets.py, que no necesita verificar eso)."""

    def __init__(self) -> None:
        self.mensajes: list[dict] = []

    async def send_json(self, mensaje: dict) -> None:
        self.mensajes.append(mensaje)

    async def close(self, code: int = 1000) -> None:
        pass


def _candidato(nodo_id: str, modelo_hash: str) -> Candidato:
    return Candidato(
        modelo_hash=modelo_hash,
        posicion=0,
        nodo=Nodo(
            nodo_id=nodo_id,
            ram_donada_mb=4096,
            cores_donados=2,
            tiene_gpu=False,
            tokens_por_segundo=3.0,
            estado=EstadoNodo.CONECTADO,
        ),
    )


def _app_falsa() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            repositorio_trabajos=RepositorioTrabajosEnMemoria(),
            repositorio_candidatos=RepositorioCandidatosEnMemoria(),
            gestor_conexiones=GestorConexiones(),
        )
    )


@pytest.mark.asyncio
async def test_reintentar_cola_despacha_cuando_hay_canal_abierto() -> None:
    app = _app_falsa()
    modelo = "hash-reintento-1"
    await app.state.repositorio_candidatos.registrar(_candidato("n0", modelo))

    trabajo = Trabajo(
        trabajo_id="t1", modelo_hash=modelo, usuario_id="u1",
        prompt="prompt original de la consulta",
        cadena_nodo_ids=["n0"], estado=EstadoTrabajo.EN_COLA,
    )
    await app.state.repositorio_trabajos.guardar(trabajo)

    websocket = WebSocketFalso()
    await app.state.gestor_conexiones.conectar("n0", websocket)

    despachados = await reintentar_cola(app)

    assert despachados == ["t1"]
    assert websocket.mensajes[0]["trabajo_id"] == "t1"
    assert websocket.mensajes[0]["tipo"] == "asignacion"
    # El reintento no debe perder el prompt que traía el trabajo.
    assert websocket.mensajes[0]["prompt"] == "prompt original de la consulta"
    actualizado = await app.state.repositorio_trabajos.obtener("t1")
    assert actualizado.estado is EstadoTrabajo.EN_CURSO


@pytest.mark.asyncio
async def test_reintentar_cola_no_hace_nada_sin_canal_abierto() -> None:
    app = _app_falsa()
    modelo = "hash-reintento-2"
    await app.state.repositorio_candidatos.registrar(_candidato("n0", modelo))
    await app.state.repositorio_trabajos.guardar(
        Trabajo(
            trabajo_id="t1", modelo_hash=modelo, usuario_id="u1",
            cadena_nodo_ids=["n0"], estado=EstadoTrabajo.EN_COLA,
        )
    )
    # Sin `gestor_conexiones.conectar`: no hay canal abierto para n0.

    despachados = await reintentar_cola(app)

    assert despachados == []
    trabajo = await app.state.repositorio_trabajos.obtener("t1")
    assert trabajo.estado is EstadoTrabajo.EN_COLA


@pytest.mark.asyncio
async def test_reintentar_cola_sigue_sin_candidatos_no_falla() -> None:
    app = _app_falsa()
    # Ningún candidato registrado para este modelo todavía.
    await app.state.repositorio_trabajos.guardar(
        Trabajo(
            trabajo_id="t1", modelo_hash="hash-sin-candidatos", usuario_id="u1",
            cadena_nodo_ids=["n0"], estado=EstadoTrabajo.EN_COLA,
        )
    )

    despachados = await reintentar_cola(app)

    assert despachados == []
    trabajo = await app.state.repositorio_trabajos.obtener("t1")
    assert trabajo.estado is EstadoTrabajo.EN_COLA


@pytest.mark.asyncio
async def test_reintentar_cola_usa_un_candidato_nuevo_si_el_original_ya_no_esta() -> None:
    """El trabajo se creó cuando solo estaba `n0` disponible, pero `n0` se
    cayó y ahora el único candidato conectado es `n1`. El reintento debe
    replanificar, no solo reintentar contra `n0`."""
    app = _app_falsa()
    modelo = "hash-reintento-3"
    await app.state.repositorio_candidatos.registrar(_candidato("n1", modelo))

    trabajo = Trabajo(
        trabajo_id="t1", modelo_hash=modelo, usuario_id="u1",
        cadena_nodo_ids=["n0"],  # el candidato original, ya no registrado
        estado=EstadoTrabajo.EN_COLA,
    )
    await app.state.repositorio_trabajos.guardar(trabajo)

    websocket_n1 = WebSocketFalso()
    await app.state.gestor_conexiones.conectar("n1", websocket_n1)

    despachados = await reintentar_cola(app)

    assert despachados == ["t1"]
    assert websocket_n1.mensajes[0]["cadena"] == ["n1"]
    actualizado = await app.state.repositorio_trabajos.obtener("t1")
    assert actualizado.cadena_nodo_ids == ["n1"]
