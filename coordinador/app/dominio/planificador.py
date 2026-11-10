"""Armado de cadenas de cómputo.

El planificador es deliberadamente una función pura sin I/O: recibe el
estado de candidatos ya cargado (por el repositorio) y devuelve una
decisión. Esto lo hace testeable sin levantar base de datos ni red, y
separa la política de asignación de cómo se persiste el estado.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.dominio.nodos import Candidato


class PosicionSinCandidatosError(Exception):
    """Una posición del modelo no tiene ningún nodo disponible que la cubra."""

    def __init__(self, modelo_hash: str, posicion: int) -> None:
        self.modelo_hash = modelo_hash
        self.posicion = posicion
        super().__init__(
            f"Sin candidatos disponibles para modelo={modelo_hash} posición={posicion}"
        )


@dataclass(frozen=True, slots=True)
class Cadena:
    modelo_hash: str
    nodo_ids_en_orden: list[str]


def _agrupar_por_posicion(
    candidatos: list[Candidato], modelo_hash: str
) -> dict[int, list[Candidato]]:
    por_posicion: dict[int, list[Candidato]] = defaultdict(list)
    for candidato in candidatos:
        if candidato.modelo_hash == modelo_hash and candidato.disponible():
            por_posicion[candidato.posicion].append(candidato)
    return por_posicion


def armar_cadena(
    candidatos: list[Candidato], modelo_hash: str, total_posiciones: int
) -> Cadena:
    """Elige, para cada posición 0..total_posiciones-1, el candidato menos
    cargado (menor `consultas_en_curso`). Lanza `PosicionSinCandidatosError`
    si alguna posición no tiene ningún nodo disponible.

    Complejidad: O(n log n) por el ordenamiento de candidatos por posición,
    donde n es la cantidad de candidatos para el modelo.
    """
    por_posicion = _agrupar_por_posicion(candidatos, modelo_hash)

    nodo_ids_en_orden: list[str] = []
    for posicion in range(total_posiciones):
        disponibles = por_posicion.get(posicion, [])
        if not disponibles:
            raise PosicionSinCandidatosError(modelo_hash, posicion)
        elegido = min(disponibles, key=lambda c: c.consultas_en_curso)
        nodo_ids_en_orden.append(elegido.nodo.nodo_id)

    return Cadena(modelo_hash=modelo_hash, nodo_ids_en_orden=nodo_ids_en_orden)


def posiciones_con_un_solo_candidato(
    candidatos: list[Candidato], modelo_hash: str, total_posiciones: int
) -> list[int]:
    """Posiciones con exactamente un candidato disponible: puntos únicos de
    falla. Se usa para alertar y priorizar la asignación de nodos nuevos.
    """
    por_posicion = _agrupar_por_posicion(candidatos, modelo_hash)
    return [
        posicion
        for posicion in range(total_posiciones)
        if len(por_posicion.get(posicion, [])) == 1
    ]


def posicion_prioritaria_para_nodo_nuevo(
    candidatos: list[Candidato], modelo_hash: str, total_posiciones: int
) -> int:
    """Decide a qué posición conviene asignar un nodo que recién se conecta:
    primero cubre posiciones vacías, luego la más saturada (menos candidatos
    primero, ya que menos candidatos implica más contención por nodo).
    """
    por_posicion = _agrupar_por_posicion(candidatos, modelo_hash)
    conteos = {
        posicion: len(por_posicion.get(posicion, []))
        for posicion in range(total_posiciones)
    }
    return min(conteos, key=lambda posicion: conteos[posicion])
