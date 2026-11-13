from __future__ import annotations

import time

import pytest

from app.dominio.creditos import TipoAsiento
from app.dominio.nodos import Candidato, EstadoNodo, Nodo
from app.dominio.trabajos import EstadoTrabajo, Trabajo
from app.infraestructura.repositorios.candidatos import (
    RepositorioCandidatosEnMemoria,
    RepositorioCreditosEnMemoria,
    RepositorioTrabajosEnMemoria,
)
from app.infraestructura.repositorios.base import (
    RepositorioCandidatos,
    RepositorioCreditos,
    RepositorioTrabajos,
)


def _candidato(nodo_id: str, modelo: str = "hash-1", posicion: int = 0) -> Candidato:
    return Candidato(
        modelo_hash=modelo,
        posicion=posicion,
        nodo=Nodo(
            nodo_id=nodo_id,
            ram_donada_mb=4096,
            cores_donados=2,
            tiene_gpu=False,
            tokens_por_segundo=3.0,
            estado=EstadoNodo.CONECTADO,
        ),
    )


@pytest.mark.asyncio
async def test_repo_candidatos_memoria_implementa_protocolo() -> None:
    assert isinstance(RepositorioCandidatosEnMemoria(), RepositorioCandidatos)


@pytest.mark.asyncio
async def test_repo_candidatos_memoria_registra_y_filtra_por_modelo() -> None:
    repo = RepositorioCandidatosEnMemoria()
    await repo.registrar(_candidato("n1", modelo="hash-a"))
    await repo.registrar(_candidato("n2", modelo="hash-b"))

    clase_modelo_a = await repo.listar_por_modelo("hash-a")
    assert [c.nodo.nodo_id for c in clase_modelo_a] == ["n1"]
    assert len(await repo.listar_todos()) == 2


@pytest.mark.asyncio
async def test_repo_trabajos_memoria_implementa_protocolo_y_es_idempotente() -> None:
    repo = RepositorioTrabajosEnMemoria()
    assert isinstance(repo, RepositorioTrabajos)

    trabajo = Trabajo(
        trabajo_id="t-1",
        modelo_hash="hash",
        usuario_id="u-1",
        estado=EstadoTrabajo.EN_COLA,
    )
    await repo.guardar(trabajo)
    await repo.guardar(trabajo)  # guardar dos veces no corrompe

    assert (await repo.obtener("t-1")).usuario_id == "u-1"  # type: ignore[union-attr]
    assert await repo.obtener("t-no-existe") is None


@pytest.mark.asyncio
async def test_repo_creditos_memoria_implementa_protocolo_y_valida_monto() -> None:
    repo = RepositorioCreditosEnMemoria()
    assert isinstance(repo, RepositorioCreditos)

    await repo.registrar_asiento("c1", TipoAsiento.APORTE, 30.0)
    await repo.registrar_asiento("c1", TipoAsiento.CONSUMO, 10.0)

    aportes, consumos = await repo.saldos("c1")
    assert (aportes, consumos) == (30.0, 10.0)

    with pytest.raises(ValueError):
        await repo.registrar_asiento("c1", TipoAsiento.CONSUMO, 0)


@pytest.mark.asyncio
async def test_latido_actualiza_estado_y_carga_del_candidato() -> None:
    repo = RepositorioCandidatosEnMemoria()
    await repo.registrar(_candidato("n1"))

    actualizado = await repo.actualizar_latido(
        "n1", EstadoNodo.OCUPADO, consultas_en_curso=2, momento_unix=100.0
    )

    assert actualizado is True
    candidato = (await repo.listar_por_modelo("hash-1"))[0]
    assert candidato.nodo.estado is EstadoNodo.OCUPADO
    assert candidato.consultas_en_curso == 2


@pytest.mark.asyncio
async def test_latido_de_nodo_desconocido_devuelve_false() -> None:
    repo = RepositorioCandidatosEnMemoria()

    assert (
        await repo.actualizar_latido(
            "fantasma", EstadoNodo.CONECTADO, consultas_en_curso=0, momento_unix=100.0
        )
        is False
    )


@pytest.mark.asyncio
async def test_vigilante_marca_caidos_y_no_repite() -> None:
    repo = RepositorioCandidatosEnMemoria()
    await repo.registrar(_candidato("n1"))
    await repo.registrar(_candidato("n2"))
    await repo.actualizar_latido("n1", EstadoNodo.CONECTADO, 0, momento_unix=1_000.0)
    await repo.actualizar_latido("n2", EstadoNodo.CONECTADO, 0, momento_unix=1_095.0)

    caidos = await repo.marcar_caidos_sin_latido(ahora_unix=1_100.0, timeout_s=30)

    assert caidos == ["n1"]
    # Una segunda pasada no vuelve a reportar al ya caído (n2 sigue al día).
    assert await repo.marcar_caidos_sin_latido(ahora_unix=1_110.0, timeout_s=30) == []


@pytest.mark.asyncio
async def test_vigilante_de_trabajos_marca_vencidos_los_en_curso_y_no_repite() -> None:
    repo = RepositorioTrabajosEnMemoria()
    await repo.guardar(
        Trabajo(trabajo_id="t-1", modelo_hash="hash", usuario_id="u-1", estado=EstadoTrabajo.EN_CURSO)
    )
    # `guardar` estampa el momento real internamente (igual que un latido
    # real), así que el "ahora" sintético tiene que ser posterior a eso.
    ahora = time.time()

    vencidos = await repo.marcar_vencidos(ahora_unix=ahora + 100, timeout_s=30)

    assert vencidos == ["t-1"]
    trabajo = await repo.obtener("t-1")
    assert trabajo.estado is EstadoTrabajo.FALLIDO
    # Segunda pasada: ya está en estado terminal, no se vuelve a reportar.
    assert await repo.marcar_vencidos(ahora_unix=ahora + 200, timeout_s=30) == []


@pytest.mark.asyncio
async def test_vigilante_de_trabajos_ignora_en_cola_y_terminales() -> None:
    repo = RepositorioTrabajosEnMemoria()
    await repo.guardar(
        Trabajo(trabajo_id="en-cola", modelo_hash="hash", usuario_id="u-1", estado=EstadoTrabajo.EN_COLA)
    )
    await repo.guardar(
        Trabajo(
            trabajo_id="completado",
            modelo_hash="hash",
            usuario_id="u-1",
            estado=EstadoTrabajo.COMPLETADO,
            texto_resultado="ya tenía respuesta",
        )
    )
    ahora = time.time()

    assert await repo.marcar_vencidos(ahora_unix=ahora + 1_000, timeout_s=1) == []
    assert (await repo.obtener("en-cola")).estado is EstadoTrabajo.EN_COLA  # type: ignore[union-attr]
    completado = await repo.obtener("completado")
    assert completado.estado is EstadoTrabajo.COMPLETADO  # type: ignore[union-attr]
    assert completado.texto_resultado == "ya tenía respuesta"  # type: ignore[union-attr]
