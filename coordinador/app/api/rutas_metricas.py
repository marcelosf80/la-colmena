"""Métricas agregadas del coordinador (`GET /metricas`).

Endpoint de solo lectura pensado para responder las preguntas del informe:
cuántos trabajos hay por estado, tasa de error, latencia p50/p95, tokens
generados y qué reporta cada nodo conectado. No reemplaza un sistema de
observabilidad (Prometheus/Grafana) — es la base medible del prototipo.

Los cálculos viven en `app/dominio/metricas.py` (funciones puras); acá solo
se recolectan datos de los repositorios y se arma la respuesta.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencias import repo_candidatos, repo_trabajos
from app.dominio.metricas import resumen_latencias, resumen_tokens
from app.dominio.nodos import EstadoNodo
from app.dominio.trabajos import EstadoTrabajo
from app.infraestructura.repositorios.base import (
    RepositorioCandidatos,
    RepositorioTrabajos,
)

router = APIRouter(prefix="/metricas", tags=["metricas"])


@router.get("")
async def obtener_metricas(
    repositorio_trabajos: RepositorioTrabajos = Depends(repo_trabajos),
    repositorio_candidatos: RepositorioCandidatos = Depends(repo_candidatos),
) -> dict:
    trabajos = await repositorio_trabajos.listar_todos()
    candidatos = await repositorio_candidatos.listar_todos()

    por_estado = {estado.name.lower(): 0 for estado in EstadoTrabajo}
    for trabajo in trabajos:
        por_estado[trabajo.estado.name.lower()] += 1

    completados = [t for t in trabajos if t.estado is EstadoTrabajo.COMPLETADO]
    fallidos = [t for t in trabajos if t.estado is EstadoTrabajo.FALLIDO]
    resueltos = len(completados) + len(fallidos)

    latencias = [t.latencia_ms for t in completados if t.latencia_ms is not None]
    # Solo los trabajos con latencia y tokens medidos entran en la tasa
    # agregada: mezclar denominadores distintos daría un número engañoso.
    con_tokens = [
        t
        for t in completados
        if t.tokens_generados is not None and t.latencia_ms is not None
    ]
    tokens = [t.tokens_generados or 0 for t in con_tokens]
    latencias_de_tokens = [t.latencia_ms or 0 for t in con_tokens]

    # Un nodo puede aparecer en varias posiciones del mismo modelo: se
    # agrega por nodo_id para no contarlo dos veces.
    nodos: dict[str, dict] = {}
    for candidato in candidatos:
        nodo = candidato.nodo
        entrada = nodos.setdefault(
            nodo.nodo_id,
            {
                "nodo_id": nodo.nodo_id,
                "estado": nodo.estado.name.lower(),
                "tiene_gpu": nodo.tiene_gpu,
                "tokens_por_segundo": nodo.tokens_por_segundo,
                "consultas_en_curso": 0,
            },
        )
        entrada["consultas_en_curso"] = max(
            entrada["consultas_en_curso"], candidato.consultas_en_curso
        )

    nodos_por_estado = {estado.name.lower(): 0 for estado in EstadoNodo}
    for nodo in nodos.values():
        nodos_por_estado[nodo["estado"]] += 1

    return {
        "trabajos": {
            "total": len(trabajos),
            "por_estado": por_estado,
            "tasa_error": round(len(fallidos) / resueltos, 3) if resueltos else 0.0,
        },
        "latencia_ms": resumen_latencias(latencias),
        "tokens": resumen_tokens(tokens, latencias_de_tokens),
        "nodos": {
            "total": len(nodos),
            "por_estado": nodos_por_estado,
            "consultas_en_curso": sum(n["consultas_en_curso"] for n in nodos.values()),
            "tokens_por_segundo_promedio": (
                round(
                    sum(n["tokens_por_segundo"] for n in nodos.values()) / len(nodos),
                    3,
                )
                if nodos
                else 0.0
            ),
            "detalle": sorted(nodos.values(), key=lambda n: n["nodo_id"]),
        },
    }
