"""Tests de `GET /metricas` con repositorios en memoria.

Se usa `TestClient` porque el endpoint arma la respuesta a partir del estado
de `app.state`, igual que el resto de la API. Los percentiles puros se
prueban en `test_metricas.py`.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def _modelo_unico() -> str:
    return f"hash-metricas-{uuid4()}"


def _registrar(cliente: TestClient, nodo_id: str, modelo_hash: str) -> None:
    respuesta = cliente.post(
        "/nodos/registro",
        json={
            "nodo_id": nodo_id,
            "ram_donada_mb": 4096,
            "cores_donados": 4,
            "tiene_gpu": True,
            "modelo_hash": modelo_hash,
            "posicion": 0,
            "tokens_por_segundo": 12.5,
        },
    )
    assert respuesta.status_code == 201


def test_metricas_sin_trabajos_devuelve_ceros_coherentes() -> None:
    with TestClient(app) as cliente:
        respuesta = cliente.get("/metricas")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["trabajos"]["total"] == 0
    assert cuerpo["trabajos"]["tasa_error"] == 0.0
    assert cuerpo["latencia_ms"] == {"p50": None, "p95": None, "muestra": 0}
    assert cuerpo["tokens"] == {"generados": 0, "por_segundo": 0.0}


def test_metricas_agrega_latencia_tokens_y_detalle_de_nodos() -> None:
    modelo = _modelo_unico()
    nodo_id = f"nodo-metricas-{uuid4()}"
    with TestClient(app) as cliente:
        _registrar(cliente, nodo_id, modelo)

        with cliente.websocket_connect(f"/ws/nodos/{nodo_id}") as ws:
            consulta = cliente.post(
                "/consultas",
                json={
                    "usuario_id": "usuario-metricas",
                    "modelo_hash": modelo,
                    "total_posiciones": 1,
                    "prompt": "contame algo",
                },
            )
            assert consulta.status_code == 202
            trabajo_id = consulta.json()["trabajo_id"]
            asignacion = ws.receive_json()
            assert asignacion["trabajo_id"] == trabajo_id

            ws.send_json(
                {
                    "tipo": "resultado",
                    "trabajo_id": trabajo_id,
                    "exito": True,
                    "texto": "algo",
                    "rol": "primaria",
                    "tokens": 9,
                }
            )
            # El coordinador procesa el mensaje en su loop: se consulta el
            # estado hasta que el resultado quedó asentado.
            for _ in range(50):
                detalle = cliente.get(f"/consultas/{trabajo_id}").json()
                if detalle["estado"] == "completado":
                    break
            assert detalle["estado"] == "completado"

        metricas = cliente.get("/metricas").json()

    assert metricas["trabajos"]["por_estado"]["completado"] >= 1
    assert metricas["tokens"]["generados"] >= 9
    assert metricas["latencia_ms"]["muestra"] >= 1
    assert metricas["latencia_ms"]["p50"] is not None
    assert metricas["nodos"]["total"] >= 1
    nodo = next(n for n in metricas["nodos"]["detalle"] if n["nodo_id"] == nodo_id)
    assert nodo["tiene_gpu"] is True
    assert nodo["tokens_por_segundo"] == 12.5
    assert detalle["latencia_ms"] is not None
    assert detalle["tokens_generados"] == 9
