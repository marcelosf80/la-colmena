from __future__ import annotations

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
