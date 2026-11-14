from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.dependencias import repo_candidatos, repo_trabajos
from app.config import configuracion
from app.dominio.planificador import PosicionSinCandidatosError, armar_cadena
from app.dominio.trabajos import EstadoTrabajo, Trabajo, construir_asignacion
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
    # conectado, el trabajo queda EN_COLA — lo redespacha el vigilante de
    # cola (ver `reintentar_cola` más abajo).
    primero = trabajo.cadena_nodo_ids[0]
    asignacion = construir_asignacion(
        trabajo, timeout_ms=int(configuracion.trabajo_timeout_s * 1000)
    )
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


async def reintentar_cola(app) -> list[str]:
    """Reintenta despachar los trabajos EN_COLA. Lo llama el vigilante de
    `main.py` cada `reintento_cola_s`, y también los tests directamente
    (sin esperar el intervalo real).

    Para cada trabajo EN_COLA vuelve a correr el planificador con los
    candidatos actuales — pueden ser distintos a los que había cuando se
    creó el trabajo, por eso no alcanza con reintentar contra la cadena ya
    guardada — y, si arma una cadena, intenta despachar al primer nodo. Si
    ese nodo todavía no tiene canal abierto, el trabajo sigue EN_COLA y se
    reintenta en la próxima pasada; eso no es un error, solo se loguea el
    éxito. Devuelve los trabajo_id que se lograron despachar en esta pasada.
    """
    repositorio_trabajos: RepositorioTrabajos = app.state.repositorio_trabajos
    repositorio_candidatos: RepositorioCandidatos = app.state.repositorio_candidatos
    gestor = app.state.gestor_conexiones

    despachados: list[str] = []
    for trabajo in await repositorio_trabajos.listar_por_estado(EstadoTrabajo.EN_COLA):
        total_posiciones = len(trabajo.cadena_nodo_ids) or 1
        candidatos = await repositorio_candidatos.listar_por_modelo(trabajo.modelo_hash)
        try:
            cadena = armar_cadena(candidatos, trabajo.modelo_hash, total_posiciones)
        except PosicionSinCandidatosError:
            continue  # sigue sin candidatos para alguna posición: se reintenta después

        trabajo.cadena_nodo_ids = cadena.nodo_ids_en_orden
        asignacion = construir_asignacion(
            trabajo, timeout_ms=int(configuracion.trabajo_timeout_s * 1000)
        )
        if await gestor.enviar(cadena.nodo_ids_en_orden[0], asignacion):
            trabajo.estado = EstadoTrabajo.EN_CURSO
            despachados.append(trabajo.trabajo_id)
        await repositorio_trabajos.guardar(trabajo)

    return despachados
