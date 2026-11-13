from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.dependencias import repo_candidatos, repo_trabajos
from app.config import configuracion
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
    request: Request,
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

    # Despacho al primer nodo de la cadena por WebSocket. Si no está
    # conectado, el trabajo queda EN_COLA para un futuro reintento/cola.
    primero = trabajo.cadena_nodo_ids[0]
    asignacion = {
        "tipo": "asignacion",
        "trabajo_id": trabajo.trabajo_id,
        "modelo_hash": trabajo.modelo_hash,
        "posicion": 0,
        "cadena": trabajo.cadena_nodo_ids,
        "siguiente_nodo_id": (
            trabajo.cadena_nodo_ids[1] if len(trabajo.cadena_nodo_ids) > 1 else None
        ),
        "timeout_ms": int(configuracion.trabajo_timeout_s * 1000),
    }
    despachado = await request.app.state.gestor_conexiones.enviar(primero, asignacion)
    if despachado:
        trabajo.estado = EstadoTrabajo.EN_CURSO

    await repositorio_trabajos.guardar(trabajo)
    return {
        "trabajo_id": trabajo.trabajo_id,
        "cadena": trabajo.cadena_nodo_ids,
        "estado": trabajo.estado.name.lower(),
        "despachado": despachado,
    }


@router.get("/{trabajo_id}")
async def consultar_trabajo(
    trabajo_id: str,
    repositorio_trabajos: RepositorioTrabajos = Depends(repo_trabajos),
) -> dict:
    trabajo = await repositorio_trabajos.obtener(trabajo_id)
    if trabajo is None:
        raise HTTPException(status_code=404, detail="Trabajo desconocido")
    return {
        "trabajo_id": trabajo.trabajo_id,
        "usuario_id": trabajo.usuario_id,
        "modelo_hash": trabajo.modelo_hash,
        "cadena": trabajo.cadena_nodo_ids,
        "estado": trabajo.estado.name.lower(),
        "texto_resultado": trabajo.texto_resultado,
        "error": trabajo.error,
    }
