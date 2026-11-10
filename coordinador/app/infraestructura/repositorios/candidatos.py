"""Repositorio en memoria. Reemplazar por una implementación Postgres cuando
se defina el esquema de persistencia — la interfaz pública se mantiene igual
para no acoplar el dominio a la implementación (principio de inversión de
dependencias).
"""

from __future__ import annotations

from app.dominio.nodos import Candidato


class RepositorioCandidatosEnMemoria:
    def __init__(self) -> None:
        self._candidatos: dict[str, Candidato] = {}

    def registrar(self, candidato: Candidato) -> None:
        self._candidatos[candidato.nodo.nodo_id] = candidato

    def listar_por_modelo(self, modelo_hash: str) -> list[Candidato]:
        return [c for c in self._candidatos.values() if c.modelo_hash == modelo_hash]

    def listar_todos(self) -> list[Candidato]:
        return list(self._candidatos.values())
