from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.dominio.nodos import Candidato, EstadoNodo, Nodo
from app.infraestructura.repositorios.candidatos import RepositorioCandidatosEnMemoria

router = APIRouter(prefix="/nodos", tags=["nodos"])

# Instancia única para el MVP en memoria. Pasará a inyección de dependencias
# de FastAPI cuando se conecte Postgres.
_repositorio = RepositorioCandidatosEnMemoria()


class RegistroNodoRequest(BaseModel):
    nodo_id: str
    ram_donada_mb: int = Field(gt=0)
    cores_donados: int = Field(gt=0)
    tiene_gpu: bool
    modelo_hash: str
    posicion: int = Field(ge=0)
    # 0.0 significa "benchmark pendiente": el nodo se registra igual y
    # reporta su capacidad real en el primer heartbeat (Fase 1).
    tokens_por_segundo: float = Field(ge=0)


@router.post("/registro", status_code=201)
def registrar_nodo(payload: RegistroNodoRequest) -> dict[str, str]:
    nodo = Nodo(
        nodo_id=payload.nodo_id,
        ram_donada_mb=payload.ram_donada_mb,
        cores_donados=payload.cores_donados,
        tiene_gpu=payload.tiene_gpu,
        tokens_por_segundo=payload.tokens_por_segundo,
        estado=EstadoNodo.CONECTADO,
    )
    candidato = Candidato(
        modelo_hash=payload.modelo_hash,
        posicion=payload.posicion,
        nodo=nodo,
    )
    _repositorio.registrar(candidato)
    return {"estado": "registrado", "nodo_id": nodo.nodo_id}


@router.get("/{modelo_hash}")
def listar_candidatos(modelo_hash: str) -> list[dict]:
    candidatos = _repositorio.listar_por_modelo(modelo_hash)
    if not candidatos:
        raise HTTPException(status_code=404, detail="Sin nodos para ese modelo")
    return [
        {
            "nodo_id": c.nodo.nodo_id,
            "posicion": c.posicion,
            "consultas_en_curso": c.consultas_en_curso,
            "estado": c.nodo.estado.name,
        }
        for c in candidatos
    ]


def obtener_repositorio() -> RepositorioCandidatosEnMemoria:
    return _repositorio
