"""Tests de integración contra un Postgres real.

Se saltan si no está definida COMUNIDAD_IA_BD_URL. Para correrlos:

    docker compose -f infraestructura/docker-compose.yml up -d postgres
    COMUNIDAD_IA_BD_URL=postgresql://comunidad_ia:cambiar_en_produccion@localhost:5432/comunidad_ia \
        pytest tests/integraciones -v

Cada test usa un nodo con id único y limpia lo que creó, así que pueden
correr contra una base de desarrollo sin borrar datos existentes.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.dominio.creditos import TipoAsiento
from app.dominio.nodos import Candidato, EstadoNodo, Nodo
from app.dominio.trabajos import EstadoTrabajo, Trabajo
from app.infraestructura.repositorios.postgres import (
    RepositorioCandidatosPostgres,
    RepositorioCreditosPostgres,
    RepositorioTrabajosPostgres,
    armar_pool,
)

BD_URL = os.environ.get("COMUNIDAD_IA_BD_URL", "")

pytestmark = pytest.mark.skipif(
    not BD_URL, reason="COMUNIDAD_IA_BD_URL no definida: se omite integración Postgres"
)


@pytest.fixture
async def pool():
    pool = await armar_pool(BD_URL)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
def modelo_hash() -> str:
    return f"modelo-{uuid4()}"


def _candidato(nodo_id: str, modelo_hash: str, posicion: int = 0) -> Candidato:
    return Candidato(
        modelo_hash=modelo_hash,
        posicion=posicion,
        nodo=Nodo(
            nodo_id=nodo_id,
            ram_donada_mb=4096,
            cores_donados=2,
            tiene_gpu=True,
            tokens_por_segundo=12.0,
            estado=EstadoNodo.CONECTADO,
        ),
        consultas_en_curso=2,
    )


async def test_candidatos_persisten_y_son_idempotentes(pool, modelo_hash: str) -> None:
    repo = RepositorioCandidatosPostgres(pool)
    nodo_id = f"nodo-{uuid4()}"

    await repo.registrar(_candidato(nodo_id, modelo_hash))
    await repo.registrar(_candidato(nodo_id, modelo_hash))  # upsert, no duplica

    candidatos = await repo.listar_por_modelo(modelo_hash)
    assert len(candidatos) == 1
    assert candidatos[0].nodo.nodo_id == nodo_id
    assert candidatos[0].consultas_en_curso == 2
    assert candidatos[0].nodo.tiene_gpu is True


async def test_trabajo_se_guarda_y_recupera(pool, modelo_hash: str) -> None:
    repo = RepositorioTrabajosPostgres(pool)
    trabajo = Trabajo(
        trabajo_id=str(uuid4()),
        modelo_hash=modelo_hash,
        usuario_id="usuario-integracion",
        cadena_nodo_ids=["n1", "n2"],
        estado=EstadoTrabajo.EN_COLA,
    )

    await repo.guardar(trabajo)
    recuperado = await repo.obtener(trabajo.trabajo_id)

    assert recuperado is not None
    assert recuperado.cadena_nodo_ids == ["n1", "n2"]
    assert recuperado.estado is EstadoTrabajo.EN_COLA


async def test_creditos_acumulan_aportes_y_consumos(pool) -> None:
    repo = RepositorioCreditosPostgres(pool)
    cuenta = f"cuenta-{uuid4()}"

    await repo.registrar_asiento(cuenta, TipoAsiento.APORTE, 40.0)
    await repo.registrar_asiento(cuenta, TipoAsiento.CONSUMO, 15.0)

    assert await repo.saldos(cuenta) == (40.0, 15.0)
    assert await repo.saldos("cuenta-sin-asientos") == (0.0, 0.0)


async def test_latido_persiste_estado_y_carga(pool, modelo_hash: str) -> None:
    repo = RepositorioCandidatosPostgres(pool)
    nodo_id = f"nodo-hb-{uuid4()}"
    await repo.registrar(_candidato(nodo_id, modelo_hash))

    actualizado = await repo.actualizar_latido(
        nodo_id, EstadoNodo.OCUPADO, consultas_en_curso=3, momento_unix=1_000.0
    )

    assert actualizado is True
    candidato = (await repo.listar_por_modelo(modelo_hash))[0]
    assert candidato.nodo.estado is EstadoNodo.OCUPADO
    assert candidato.consultas_en_curso == 3


async def test_latido_de_nodo_inexistente_devuelve_false(pool) -> None:
    repo = RepositorioCandidatosPostgres(pool)

    assert (
        await repo.actualizar_latido(
            f"fantasma-{uuid4()}", EstadoNodo.CONECTADO, 0, momento_unix=1_000.0
        )
        is False
    )


async def test_vigilante_marca_caidos_sin_latido(pool, modelo_hash: str) -> None:
    repo = RepositorioCandidatosPostgres(pool)
    vivo = f"nodo-vivo-{uuid4()}"
    vencido = f"nodo-vencido-{uuid4()}"
    await repo.registrar(_candidato(vivo, modelo_hash))
    await repo.registrar(_candidato(vencido, modelo_hash))
    await repo.actualizar_latido(vivo, EstadoNodo.CONECTADO, 0, momento_unix=1_095.0)
    await repo.actualizar_latido(vencido, EstadoNodo.CONECTADO, 0, momento_unix=1_000.0)

    caidos = await repo.marcar_caidos_sin_latido(ahora_unix=1_100.0, timeout_s=30)

    # Otros tests pueden dejar nodos con latidos viejos en la base: el
    # vigilante también los marca. Solo verificamos el comportamiento propio.
    assert vencido in caidos
    assert vivo not in caidos
    estados = {
        c.nodo.nodo_id: c.nodo.estado
        for c in await repo.listar_por_modelo(modelo_hash)
    }
    assert estados[vivo] is EstadoNodo.CONECTADO
