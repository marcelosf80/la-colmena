from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.rutas_nodos import obtener_repositorio
from app.dominio.planificador import PosicionSinCandidatosError, armar_cadena

router = APIRouter(prefix="/consultas", tags=["consultas"])


class ConsultaRequest(BaseModel):
    usuario_id: str
    modelo_hash: str
    total_posiciones: int
    prompt: str


@router.post("", status_code=202)
def enviar_consulta(payload: ConsultaRequest) -> dict:
    repositorio = obtener_repositorio()
    candidatos = repositorio.listar_por_modelo(payload.modelo_hash)
    try:
        cadena = armar_cadena(candidatos, payload.modelo_hash, payload.total_posiciones)
    except PosicionSinCandidatosError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    trabajo_id = str(uuid4())
    # TODO: persistir el Trabajo y despachar la cadena por WebSocket a los
    # nodos involucrados. Placeholder hasta definir el transporte (Fase 1).
    return {
        "trabajo_id": trabajo_id,
        "cadena": cadena.nodo_ids_en_orden,
        "estado": "en_cola",
    }
