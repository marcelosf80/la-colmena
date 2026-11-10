from __future__ import annotations

import pytest

from app.dominio.nodos import Candidato, EstadoNodo, Nodo
from app.dominio.planificador import (
    PosicionSinCandidatosError,
    armar_cadena,
    posicion_prioritaria_para_nodo_nuevo,
    posiciones_con_un_solo_candidato,
)

MODELO = "hash-modelo-70b"


def _nodo(nodo_id: str, estado: EstadoNodo = EstadoNodo.CONECTADO) -> Nodo:
    return Nodo(
        nodo_id=nodo_id,
        ram_donada_mb=8192,
        cores_donados=4,
        tiene_gpu=False,
        tokens_por_segundo=5.0,
        estado=estado,
    )


def test_arma_cadena_eligiendo_candidato_menos_cargado_por_posicion() -> None:
    candidatos = [
        Candidato(MODELO, posicion=0, nodo=_nodo("n1"), consultas_en_curso=3),
        Candidato(MODELO, posicion=0, nodo=_nodo("n2"), consultas_en_curso=1),
        Candidato(MODELO, posicion=1, nodo=_nodo("n3"), consultas_en_curso=0),
    ]

    cadena = armar_cadena(candidatos, MODELO, total_posiciones=2)

    assert cadena.nodo_ids_en_orden == ["n2", "n3"]


def test_lanza_error_si_falta_un_candidato_en_alguna_posicion() -> None:
    candidatos = [Candidato(MODELO, posicion=0, nodo=_nodo("n1"))]

    with pytest.raises(PosicionSinCandidatosError) as excinfo:
        armar_cadena(candidatos, MODELO, total_posiciones=2)

    assert excinfo.value.posicion == 1


def test_ignora_candidatos_de_otro_modelo() -> None:
    candidatos = [
        Candidato("otro-modelo", posicion=0, nodo=_nodo("n1")),
        Candidato(MODELO, posicion=0, nodo=_nodo("n2")),
    ]

    cadena = armar_cadena(candidatos, MODELO, total_posiciones=1)

    assert cadena.nodo_ids_en_orden == ["n2"]


def test_ignora_candidatos_caidos() -> None:
    candidatos = [
        Candidato(MODELO, posicion=0, nodo=_nodo("n1", EstadoNodo.CAIDO), consultas_en_curso=0),
        Candidato(MODELO, posicion=0, nodo=_nodo("n2"), consultas_en_curso=5),
    ]

    cadena = armar_cadena(candidatos, MODELO, total_posiciones=1)

    assert cadena.nodo_ids_en_orden == ["n2"]


def test_detecta_posiciones_con_un_solo_candidato() -> None:
    candidatos = [
        Candidato(MODELO, posicion=0, nodo=_nodo("n1")),
        Candidato(MODELO, posicion=1, nodo=_nodo("n2")),
        Candidato(MODELO, posicion=1, nodo=_nodo("n3")),
    ]

    resultado = posiciones_con_un_solo_candidato(candidatos, MODELO, total_posiciones=2)

    assert resultado == [0]


def test_prioriza_posicion_vacia_para_nodo_nuevo() -> None:
    candidatos = [
        Candidato(MODELO, posicion=0, nodo=_nodo("n1")),
        Candidato(MODELO, posicion=0, nodo=_nodo("n2")),
    ]

    posicion = posicion_prioritaria_para_nodo_nuevo(candidatos, MODELO, total_posiciones=3)

    assert posicion in (1, 2)  # posiciones sin ningún candidato todavía
