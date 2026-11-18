from __future__ import annotations

import time

import pytest

from app.api.websockets import GestorConexiones, _procesar_resultado, despedir_nodo
from app.dominio.nodos import Candidato, EstadoNodo, Nodo
from app.dominio.trabajos import ROL_VERIFICACION, EstadoTrabajo, Trabajo
from app.infraestructura.repositorios.candidatos import (
    RepositorioCandidatosEnMemoria,
    RepositorioCreditosEnMemoria,
    RepositorioTrabajosEnMemoria,
)


class WebSocketFalso:
    """Doble de prueba: solo lo que usa GestorConexiones/despedir_nodo."""

    def __init__(self) -> None:
        self.cerrado = False

    async def close(self, code: int = 1000) -> None:
        self.cerrado = True

    async def send_json(self, mensaje: dict) -> None:
        pass


def _candidato(nodo_id: str) -> Candidato:
    return Candidato(
        modelo_hash="hash-1",
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


def _repos() -> tuple[RepositorioTrabajosEnMemoria, RepositorioCreditosEnMemoria]:
    return RepositorioTrabajosEnMemoria(), RepositorioCreditosEnMemoria()


@pytest.mark.asyncio
async def test_despedir_nodo_marca_caido_y_libera_la_conexion() -> None:
    gestor = GestorConexiones()
    repositorio = RepositorioCandidatosEnMemoria()
    websocket = WebSocketFalso()
    await repositorio.registrar(_candidato("n1"))
    await gestor.conectar("n1", websocket)
    assert gestor.conectados() == ["n1"]

    await despedir_nodo(gestor, repositorio, "n1", websocket)

    assert gestor.conectados() == []
    candidato = (await repositorio.listar_por_modelo("hash-1"))[0]
    assert candidato.nodo.estado is EstadoNodo.CAIDO


@pytest.mark.asyncio
async def test_despedir_ignora_conexiones_que_ya_no_estan_registradas() -> None:
    """Si el nodo reconectó, la desconexión de la conexión vieja no debe
    marcar CAIDO al nodo (que ahora está conectado de nuevo)."""
    gestor = GestorConexiones()
    repositorio = RepositorioCandidatosEnMemoria()
    viejo = WebSocketFalso()
    nuevo = WebSocketFalso()
    await repositorio.registrar(_candidato("n1"))

    await gestor.conectar("n1", viejo)
    await gestor.conectar("n1", nuevo)  # reconexión reemplaza a la vieja
    assert viejo.cerrado is True

    await despedir_nodo(gestor, repositorio, "n1", viejo)

    # La conexión registrada es la nueva: nada cambió.
    assert gestor.conectados() == ["n1"]
    candidato = (await repositorio.listar_por_modelo("hash-1"))[0]
    assert candidato.nodo.estado is EstadoNodo.CONECTADO


@pytest.mark.asyncio
async def test_enviar_falla_limpio_sin_conexion() -> None:
    gestor = GestorConexiones()

    assert await gestor.enviar("fantasma", {"tipo": "asignacion"}) is False


@pytest.mark.asyncio
async def test_enviar_entrega_y_limpia_conexiones_rotas() -> None:
    gestor = GestorConexiones()

    class WebSocketRoto:
        async def send_json(self, mensaje: dict) -> None:
            raise RuntimeError("socket cerrado")

    await gestor.conectar("n1", WebSocketRoto())

    assert await gestor.enviar("n1", {"tipo": "asignacion"}) is False
    assert gestor.conectados() == []


@pytest.mark.asyncio
async def test_procesar_resultado_exitoso_completa_el_trabajo() -> None:
    repositorio, creditos = _repos()
    await repositorio.guardar(
        Trabajo(trabajo_id="t1", modelo_hash="hash-1", usuario_id="u1", estado=EstadoTrabajo.EN_CURSO)
    )

    await _procesar_resultado(
        repositorio,
        creditos,
        "n0",
        {"tipo": "resultado", "trabajo_id": "t1", "exito": True, "texto": "hola"},
    )

    trabajo = await repositorio.obtener("t1")
    assert trabajo.estado is EstadoTrabajo.COMPLETADO
    assert trabajo.texto_resultado == "hola"


@pytest.mark.asyncio
async def test_procesar_resultado_anota_latencia_y_tokens_si_hubo_despacho() -> None:
    repositorio, creditos = _repos()
    despachado = time.time() - 1.5
    await repositorio.guardar(
        Trabajo(
            trabajo_id="t1",
            modelo_hash="hash-1",
            usuario_id="u1",
            estado=EstadoTrabajo.EN_CURSO,
            despachado_en_unix=despachado,
        )
    )

    await _procesar_resultado(
        repositorio,
        creditos,
        "n0",
        {
            "tipo": "resultado",
            "trabajo_id": "t1",
            "exito": True,
            "texto": "hola",
            "tokens": 42,
        },
    )

    trabajo = await repositorio.obtener("t1")
    assert trabajo.latencia_ms is not None
    assert trabajo.latencia_ms >= 1_400  # ~1.5 s
    assert trabajo.tokens_generados == 42


@pytest.mark.asyncio
async def test_procesar_resultado_sin_despacho_no_inventa_latencia() -> None:
    # Trabajos viejos (o creados sin despacho) no tienen referencia temporal.
    repositorio, creditos = _repos()
    await repositorio.guardar(
        Trabajo(trabajo_id="t1", modelo_hash="hash-1", usuario_id="u1", estado=EstadoTrabajo.EN_CURSO)
    )

    await _procesar_resultado(
        repositorio,
        creditos,
        "n0",
        {"tipo": "resultado", "trabajo_id": "t1", "exito": True, "texto": "hola", "tokens": 7},
    )

    trabajo = await repositorio.obtener("t1")
    assert trabajo.latencia_ms is None
    assert trabajo.tokens_generados is None


@pytest.mark.asyncio
async def test_procesar_resultado_fallido_marca_fallido_con_el_error() -> None:
    repositorio, creditos = _repos()
    await repositorio.guardar(
        Trabajo(trabajo_id="t1", modelo_hash="hash-1", usuario_id="u1", estado=EstadoTrabajo.EN_CURSO)
    )

    await _procesar_resultado(
        repositorio,
        creditos,
        "n0",
        {"tipo": "resultado", "trabajo_id": "t1", "exito": False, "error": "timeout"},
    )

    trabajo = await repositorio.obtener("t1")
    assert trabajo.estado is EstadoTrabajo.FALLIDO
    assert trabajo.error == "timeout"


@pytest.mark.asyncio
async def test_procesar_resultado_sin_trabajo_id_no_rompe_el_canal() -> None:
    repositorio, creditos = _repos()
    # No debe lanzar, solo loguear y seguir.
    await _procesar_resultado(repositorio, creditos, "n0", {"tipo": "resultado", "exito": True})


@pytest.mark.asyncio
async def test_procesar_resultado_de_trabajo_desconocido_no_rompe_el_canal() -> None:
    repositorio, creditos = _repos()
    await _procesar_resultado(
        repositorio,
        creditos,
        "n0",
        {"tipo": "resultado", "trabajo_id": "no-existe", "exito": True, "texto": "x"},
    )
    assert await repositorio.obtener("no-existe") is None


@pytest.mark.asyncio
async def test_procesar_resultado_sin_rol_se_trata_como_primaria() -> None:
    # Compatibilidad: un nodo viejo que no mande "rol" no debe romper nada,
    # y el trabajo se resuelve igual que antes de que existiera el campo.
    repositorio, creditos = _repos()
    await repositorio.guardar(
        Trabajo(trabajo_id="t1", modelo_hash="hash-1", usuario_id="u1", estado=EstadoTrabajo.EN_CURSO)
    )

    await _procesar_resultado(
        repositorio, creditos, "n0", {"tipo": "resultado", "trabajo_id": "t1", "exito": True, "texto": "hola"}
    )

    trabajo = await repositorio.obtener("t1")
    assert trabajo.estado is EstadoTrabajo.COMPLETADO


@pytest.mark.asyncio
async def test_procesar_resultado_con_verificacion_espera_las_dos_copias() -> None:
    repositorio, creditos = _repos()
    await repositorio.guardar(
        Trabajo(
            trabajo_id="t1",
            modelo_hash="hash-1",
            usuario_id="u1",
            cadena_nodo_ids=["n0"],
            cadena_verificacion_nodo_ids=["n1"],
            estado=EstadoTrabajo.EN_CURSO,
        )
    )

    await _procesar_resultado(
        repositorio, creditos, "n0", {"tipo": "resultado", "trabajo_id": "t1", "exito": True, "texto": "hola"}
    )
    trabajo = await repositorio.obtener("t1")
    assert trabajo.estado is EstadoTrabajo.VERIFICANDO

    await _procesar_resultado(
        repositorio,
        creditos,
        "n1",
        {"tipo": "resultado", "trabajo_id": "t1", "exito": True, "texto": "hola", "rol": ROL_VERIFICACION},
    )
    trabajo = await repositorio.obtener("t1")
    assert trabajo.estado is EstadoTrabajo.COMPLETADO
    assert trabajo.texto_resultado == "hola"


@pytest.mark.asyncio
async def test_procesar_resultado_con_verificacion_discrepancia_marca_fallido() -> None:
    repositorio, creditos = _repos()
    await repositorio.guardar(
        Trabajo(
            trabajo_id="t1",
            modelo_hash="hash-1",
            usuario_id="u1",
            cadena_nodo_ids=["n0"],
            cadena_verificacion_nodo_ids=["n1"],
            estado=EstadoTrabajo.EN_CURSO,
        )
    )

    await _procesar_resultado(
        repositorio, creditos, "n0", {"tipo": "resultado", "trabajo_id": "t1", "exito": True, "texto": "respuesta A"}
    )
    await _procesar_resultado(
        repositorio,
        creditos,
        "n1",
        {
            "tipo": "resultado",
            "trabajo_id": "t1",
            "exito": True,
            "texto": "respuesta B",
            "rol": ROL_VERIFICACION,
        },
    )

    trabajo = await repositorio.obtener("t1")
    assert trabajo.estado is EstadoTrabajo.FALLIDO
    assert "no coinciden" in trabajo.error


@pytest.mark.asyncio
async def test_procesar_resultado_exitoso_acredita_tokens_al_nodo() -> None:
    repositorio, creditos = _repos()
    await repositorio.guardar(
        Trabajo(trabajo_id="t1", modelo_hash="hash-1", usuario_id="u1", estado=EstadoTrabajo.EN_CURSO)
    )

    await _procesar_resultado(
        repositorio,
        creditos,
        "n0",
        {"tipo": "resultado", "trabajo_id": "t1", "exito": True, "texto": "hola", "tokens": 42},
    )

    aportes, _consumos = await creditos.saldos("n0")
    assert aportes == 42.0


@pytest.mark.asyncio
async def test_procesar_resultado_fallido_no_acredita_nada() -> None:
    repositorio, creditos = _repos()
    await repositorio.guardar(
        Trabajo(trabajo_id="t1", modelo_hash="hash-1", usuario_id="u1", estado=EstadoTrabajo.EN_CURSO)
    )

    await _procesar_resultado(
        repositorio,
        creditos,
        "n0",
        {"tipo": "resultado", "trabajo_id": "t1", "exito": False, "error": "timeout", "tokens": 5},
    )

    aportes, _consumos = await creditos.saldos("n0")
    assert aportes == 0.0


@pytest.mark.asyncio
async def test_procesar_resultado_verificacion_coincide_acredita_a_los_dos_nodos() -> None:
    repositorio, creditos = _repos()
    await repositorio.guardar(
        Trabajo(
            trabajo_id="t1",
            modelo_hash="hash-1",
            usuario_id="u1",
            cadena_nodo_ids=["n0"],
            cadena_verificacion_nodo_ids=["n1"],
            estado=EstadoTrabajo.EN_CURSO,
        )
    )

    await _procesar_resultado(
        repositorio,
        creditos,
        "n0",
        {"tipo": "resultado", "trabajo_id": "t1", "exito": True, "texto": "hola", "tokens": 10},
    )
    # Todavía no se acredita nada: no se sabe si va a coincidir.
    assert (await creditos.saldos("n0"))[0] == 0.0

    await _procesar_resultado(
        repositorio,
        creditos,
        "n1",
        {
            "tipo": "resultado",
            "trabajo_id": "t1",
            "exito": True,
            "texto": "hola",
            "rol": ROL_VERIFICACION,
            "tokens": 11,
        },
    )

    # Ahora sí, las dos, cada uno con lo que reportó (no se promedia).
    assert (await creditos.saldos("n0"))[0] == 10.0
    assert (await creditos.saldos("n1"))[0] == 11.0


@pytest.mark.asyncio
async def test_procesar_resultado_discrepancia_no_acredita_a_ninguno() -> None:
    repositorio, creditos = _repos()
    await repositorio.guardar(
        Trabajo(
            trabajo_id="t1",
            modelo_hash="hash-1",
            usuario_id="u1",
            cadena_nodo_ids=["n0"],
            cadena_verificacion_nodo_ids=["n1"],
            estado=EstadoTrabajo.EN_CURSO,
        )
    )

    await _procesar_resultado(
        repositorio,
        creditos,
        "n0",
        {"tipo": "resultado", "trabajo_id": "t1", "exito": True, "texto": "respuesta A", "tokens": 10},
    )
    await _procesar_resultado(
        repositorio,
        creditos,
        "n1",
        {
            "tipo": "resultado",
            "trabajo_id": "t1",
            "exito": True,
            "texto": "respuesta B",
            "rol": ROL_VERIFICACION,
            "tokens": 10,
        },
    )

    assert (await creditos.saldos("n0"))[0] == 0.0
    assert (await creditos.saldos("n1"))[0] == 0.0
