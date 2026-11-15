from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import configuracion
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

        # Al cerrarse el canal, el nodo se marca CAIDO (ver
        # test_websockets.py: el evento de desconexión lo entrega el
        # TestClient recién al cerrar el contexto, así que aquí no se puede
        # observar dentro del mismo cliente).
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


def test_verificacion_por_replicas_despacha_a_dos_nodos_independientes() -> None:
    modelo = _modelo_unico()
    nodo_a = f"nodo-verif-a-{uuid4()}"
    nodo_b = f"nodo-verif-b-{uuid4()}"
    configuracion.tasa_verificacion = 1.0  # activa para esta consulta sí o sí
    try:
        with TestClient(app) as cliente:
            _registrar(cliente, nodo_a, posicion=0, modelo_hash=modelo)
            _registrar(cliente, nodo_b, posicion=0, modelo_hash=modelo)

            with cliente.websocket_connect(f"/ws/nodos/{nodo_a}") as ws_a, cliente.websocket_connect(
                f"/ws/nodos/{nodo_b}"
            ) as ws_b:
                respuesta = cliente.post(
                    "/consultas",
                    json={
                        "usuario_id": "usuario-1",
                        "modelo_hash": modelo,
                        "total_posiciones": 1,
                        "prompt": "verificar con dos nodos",
                    },
                )
                cuerpo = respuesta.json()
                assert cuerpo["despachado"] is True
                assert cuerpo["verificacion_activa"] is True

                asignacion_a = ws_a.receive_json()
                asignacion_b = ws_b.receive_json()

                # Cada nodo recibió su propia copia con el rol correcto, y
                # ningún nodo aparece en la cadena del otro.
                roles = {asignacion_a["rol"], asignacion_b["rol"]}
                assert roles == {"primaria", "verificacion"}
                assert asignacion_a["trabajo_id"] == asignacion_b["trabajo_id"] == cuerpo["trabajo_id"]
    finally:
        configuracion.tasa_verificacion = 0.0


def test_verificacion_sin_segundo_nodo_no_bloquea_la_consulta() -> None:
    # tasa_verificacion=1.0 pero solo hay un nodo: debe despachar la copia
    # primaria igual, sin verificación (no hay con quién comparar).
    modelo = _modelo_unico()
    nodo_a = f"nodo-verif-solo-{uuid4()}"
    configuracion.tasa_verificacion = 1.0
    try:
        with TestClient(app) as cliente:
            _registrar(cliente, nodo_a, posicion=0, modelo_hash=modelo)
            with cliente.websocket_connect(f"/ws/nodos/{nodo_a}") as ws:
                respuesta = cliente.post(
                    "/consultas",
                    json={
                        "usuario_id": "usuario-1",
                        "modelo_hash": modelo,
                        "total_posiciones": 1,
                        "prompt": "un solo nodo disponible",
                    },
                )
                cuerpo = respuesta.json()
                assert cuerpo["despachado"] is True
                assert cuerpo["verificacion_activa"] is False

                asignacion = ws.receive_json()
                assert asignacion["rol"] == "primaria"
    finally:
        configuracion.tasa_verificacion = 0.0
