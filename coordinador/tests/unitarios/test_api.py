from __future__ import annotations

import time
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


def test_heartbeat_actualiza_estado_y_carga() -> None:
    modelo = _modelo_unico()
    nodo_id = f"nodo-hb-{uuid4()}"
    with TestClient(app) as cliente:
        _registrar(cliente, nodo_id, posicion=0, modelo_hash=modelo)

        respuesta = cliente.post(
            f"/nodos/{nodo_id}/heartbeat",
            json={"consultas_en_curso": 2, "acepta_trabajo": True},
        )
        assert respuesta.status_code == 200
        assert respuesta.json()["estado"] == "OCUPADO"

        estado = cliente.get(f"/nodos/{modelo}").json()[0]
        assert estado["consultas_en_curso"] == 2
        assert estado["estado"] == "OCUPADO"

        # El usuario pausa el nodo: deja de aceptar trabajo.
        respuesta = cliente.post(
            f"/nodos/{nodo_id}/heartbeat",
            json={"consultas_en_curso": 0, "acepta_trabajo": False},
        )
        assert respuesta.json()["estado"] == "CAIDO"


def test_heartbeat_de_nodo_desconocido_devuelve_404() -> None:
    with TestClient(app) as cliente:
        respuesta = cliente.post(
            f"/nodos/no-existe-{uuid4()}/heartbeat",
            json={"consultas_en_curso": 0},
        )
        assert respuesta.status_code == 404


def test_consulta_se_despacha_por_websocket_al_primer_nodo() -> None:
    modelo = _modelo_unico()
    nodo_a = f"nodo-ws-a-{uuid4()}"
    nodo_b = f"nodo-ws-b-{uuid4()}"
    with TestClient(app) as cliente:
        _registrar(cliente, nodo_a, posicion=0, modelo_hash=modelo)
        _registrar(cliente, nodo_b, posicion=1, modelo_hash=modelo)

        with cliente.websocket_connect(f"/ws/nodos/{nodo_a}") as ws:
            respuesta = cliente.post(
                "/consultas",
                json={
                    "usuario_id": "usuario-1",
                    "modelo_hash": modelo,
                    "total_posiciones": 2,
                    "prompt": "hola por ws",
                },
            )
            assert respuesta.status_code == 202
            cuerpo = respuesta.json()
            despacho_ok = cuerpo["despachado"]
            assert cuerpo["despachado"] is True
            assert cuerpo["estado"] == "en_curso"

            asignacion = ws.receive_json()
            assert asignacion["tipo"] == "asignacion"
            assert asignacion["trabajo_id"] == cuerpo["trabajo_id"]
            assert asignacion["cadena"] == [nodo_a, nodo_b]
            assert asignacion["siguiente_nodo_id"] == nodo_b

        # Al cerrarse el canal, el nodo se marca CAIDO. El cierre es
        # asincrónico en el servidor y su entrega depende de la versión de
        # starlette: esperamos hasta 10 s antes de dar el estado por bueno.
        estados: dict = {}
        for _ in range(200):
            listado = cliente.get(f"/nodos/{modelo}").json()
            estados = {c["nodo_id"]: c["estado"] for c in listado}
            if estados.get(nodo_a) == "CAIDO":
                break
            time.sleep(0.05)
        assert estados[nodo_a] == "CAIDO", (estados, despacho_ok)

        estado_trabajo = cliente.get(f"/consultas/{cuerpo['trabajo_id']}").json()
        assert estado_trabajo["estado"] == "en_curso"


def test_consulta_sin_nodo_conectado_queda_en_cola() -> None:
    modelo = _modelo_unico()
    with TestClient(app) as cliente:
        _registrar(cliente, f"nodo-sin-ws-{uuid4()}", posicion=0, modelo_hash=modelo)

        respuesta = cliente.post(
            "/consultas",
            json={
                "usuario_id": "usuario-1",
                "modelo_hash": modelo,
                "total_posiciones": 1,
                "prompt": "sin canal abierto",
            },
        )
        assert respuesta.status_code == 202
        assert respuesta.json()["despachado"] is False
        assert respuesta.json()["estado"] == "en_cola"
