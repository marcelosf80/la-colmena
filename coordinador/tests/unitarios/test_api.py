from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

MODELO = "hash-modelo-test"


def _registrar(cliente: TestClient, nodo_id: str, posicion: int) -> None:
    respuesta = cliente.post(
        "/nodos/registro",
        json={
            "nodo_id": nodo_id,
            "ram_donada_mb": 8192,
            "cores_donados": 4,
            "tiene_gpu": False,
            "modelo_hash": MODELO,
            "posicion": posicion,
            "tokens_por_segundo": 5.0,
        },
    )
    assert respuesta.status_code == 201


def test_flujo_completo_registro_listado_y_consulta() -> None:
    with TestClient(app) as cliente:
        assert cliente.get("/salud").json()["estado"] == "ok"

        _registrar(cliente, "nodo-a", posicion=0)
        _registrar(cliente, "nodo-b", posicion=1)

        listado = cliente.get(f"/nodos/{MODELO}").json()
        assert {c["nodo_id"] for c in listado} == {"nodo-a", "nodo-b"}

        consulta = cliente.post(
            "/consultas",
            json={
                "usuario_id": "usuario-1",
                "modelo_hash": MODELO,
                "total_posiciones": 2,
                "prompt": "hola colmena",
            },
        )
        assert consulta.status_code == 202
        cuerpo = consulta.json()
        assert cuerpo["cadena"] == ["nodo-a", "nodo-b"]
        assert cuerpo["estado"] == "en_cola"
        assert cuerpo["trabajo_id"]


def test_consulta_sin_candidatos_para_posicion_devuelve_503() -> None:
    with TestClient(app) as cliente:
        _registrar(cliente, "nodo-unico", posicion=0)

        consulta = cliente.post(
            "/consultas",
            json={
                "usuario_id": "usuario-1",
                "modelo_hash": MODELO,
                "total_posiciones": 2,
                "prompt": "sin nodo en posicion 1",
            },
        )
        assert consulta.status_code == 503


def test_listado_de_modelo_desconocido_devuelve_404() -> None:
    with TestClient(app) as cliente:
        assert cliente.get("/nodos/modelo-que-no-existe").status_code == 404
