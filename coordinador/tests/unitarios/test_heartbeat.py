from __future__ import annotations

from app.dominio.heartbeat import Latido, estado_efectivo, nodos_sin_latido
from app.dominio.nodos import EstadoNodo


def test_nodo_sin_trabajo_queda_conectado() -> None:
    latido = Latido(nodo_id="n1", consultas_en_curso=0)

    assert estado_efectivo(latido) is EstadoNodo.CONECTADO


def test_nodo_con_consultas_queda_ocupado() -> None:
    latido = Latido(nodo_id="n1", consultas_en_curso=3)

    assert estado_efectivo(latido) is EstadoNodo.OCUPADO


def test_nodo_que_no_acepta_trabajo_queda_caido() -> None:
    latido = Latido(nodo_id="n1", consultas_en_curso=0, acepta_trabajo=False)

    assert estado_efectivo(latido) is EstadoNodo.CAIDO


def test_detecta_nodos_con_latido_vencido() -> None:
    ahora = 1_000.0
    ultimos = {"al-dia": 990.0, "vencido": 900.0}

    assert nodos_sin_latido(ultimos, ahora, timeout_s=30) == ["vencido"]


def test_latido_exactamente_en_el_limite_no_se_marca() -> None:
    ahora = 1_000.0
    ultimos = {"limite": 970.0}

    # El timeout vence solo cuando se supera, no al alcanzarlo.
    assert nodos_sin_latido(ultimos, ahora, timeout_s=30) == []
