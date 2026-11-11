from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencias import repo_candidatos, repo_trabajos
from app.dominio.planificador import PosicionSinCandidatosError, armar_cadena
from app.dominio.trabajos import EstadoTrabajo, Trabajo
from app.infraestructura.repositorios.base import (
    RepositorioCandidatos,
    RepositorioTrabajos,
)

router = APIRouter(prefix="/consultas", tags=["consultas"])


class ConsultaRequest(BaseModel):
    usuario_id: str
    modelo_hash: str
    total_posiciones: int
    prompt: str


@router.post("", status_code=202)
async def enviar_consulta(
    payload: ConsultaRequest,
    repositorio: RepositorioCandidatos = Depends(repo_candidatos),
    repositorio_trabajos: RepositorioTrabajos = Depends(repo_trabajos),
) -> dict:
    candidatos = await repositorio.listar_por_modelo(payload.modelo_hash)
    try:
        cadena = armar_cadena(candidatos, payload.modelo_hash, payload.total_posiciones)
    except PosicionSinCandidatosError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    trabajo = Trabajo(
        trabajo_id=str(uuid4()),
        modelo_hash=payload.modelo_hash,
        usuario_id=payload.usuario_id,
        cadena_nodo_ids=cadena.nodo_ids_en_orden,
        estado=EstadoTrabajo.EN_COLA,
    )
    # TODO: despachar la cadena por WebSocket a los nodos involucrados
    # (Fase 1). El trabajo queda persistido con estado EN_COLA mientras tanto.
    await repositorio_trabajos.guardar(trabajo)
    return {
        "trabajo_id": trabajo.trabajo_id,
        "cadena": trabajo.cadena_nodo_ids,
        "estado": trabajo.estado.name.lower(),
    }
