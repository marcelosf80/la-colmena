from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def _modelo_unico() -> str:
    """Cada test usa un modelo propio: así el estado no se filtra entre
    tests aunque el repositorio sea Postgres persistente (CI)."""
    return f"hash-modelo-{uuid4()}"


def _registrar(
    cliente: TestClient, nodo_id: str, posicion: int, modelo_hash: str
) -> None:
    respuesta = cliente.post(
        "/nodos/registro",
        json={
            "nodo_id": nodo_id,
            "ram_donada_mb": 8192,
            "cores_donados": 4,
            "tiene_gpu": False,
            "modelo_hash": modelo_hash,
            "posicion": posicion,
            "tokens_por_segundo": 5.0,
        },
    )
    assert respuesta.status_code == 201


def test_flujo_completo_registro_listado_y_consulta() -> None:
    modelo = _modelo_unico()
    with TestClient(app) as cliente:
        assert cliente.get("/salud").json()["estado"] == "ok"

        _registrar(cliente, f"nodo-a-{uuid4()}", posicion=0, modelo_hash=modelo)
        _registrar(cliente, f"nodo-b-{uuid4()}", posicion=1, modelo_hash=modelo)

        listado = cliente.get(f"/nodos/{modelo}").json()
        assert len(listado) == 2
        assert {c["posicion"] for c in listado} == {0, 1}

        consulta = cliente.post(
            "/consultas",
            json={
                "usuario_id": "usuario-1",
                "modelo_hash": modelo,
                "total_posiciones": 2,
                "prompt": "hola colmena",
            },
        )
        assert consulta.status_code == 202
        cuerpo = consulta.json()
        assert len(cuerpo["cadena"]) == 2
        assert cuerpo["estado"] == "en_cola"
        assert cuerpo["trabajo_id"]


def test_consulta_sin_candidatos_para_posicion_devuelve_503() -> None:
    modelo = _modelo_unico()
    with TestClient(app) as cliente:
        _registrar(cliente, f"nodo-unico-{uuid4()}", posicion=0, modelo_hash=modelo)

        consulta = cliente.post(
            "/consultas",
            json={
                "usuario_id": "usuario-1",
                "modelo_hash": modelo,
                "total_posiciones": 2,
                "prompt": "sin nodo en posicion 1",
            },
        )
        assert consulta.status_code == 503


def test_listado_de_modelo_desconocido_devuelve_404() -> None:
    with TestClient(app) as cliente:
        assert cliente.get(f"/nodos/{_modelo_unico()}").status_code == 404
