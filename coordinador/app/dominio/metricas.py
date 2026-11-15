"""Cálculos de métricas del coordinador.

Funciones puras, sin I/O, para poder testear percentiles y resúmenes sin
levantar FastAPI ni una base de datos. El endpoint `GET /metricas`
(`app/api/rutas_metricas.py`) solo recolecta los datos y delega acá.
"""

from __future__ import annotations

from collections.abc import Sequence


def percentil(valores: Sequence[float | int], p: float) -> float | None:
    """Percentil por rango más cercano, con interpolación al índice más
    próximo. Con listas cortas (lo normal en un prototipo) es más honesto
    que inventar una interpolación lineal: devuelve un valor observado.

    Devuelve `None` si no hay muestra o si `p` está fuera de [0, 100].
    """
    if not valores or not 0 <= p <= 100:
        return None
    ordenados = sorted(valores)
    indice = round((p / 100.0) * (len(ordenados) - 1))
    indice = max(0, min(len(ordenados) - 1, indice))
    return float(ordenados[indice])


def resumen_latencias(latencias: Sequence[int]) -> dict:
    """p50/p95 y tamaño de muestra de las latencias en milisegundos."""
    return {
        "p50": percentil(latencias, 50),
        "p95": percentil(latencias, 95),
        "muestra": len(latencias),
    }


def resumen_tokens(tokens: Sequence[int], latencias_ms: Sequence[int]) -> dict:
    """Tokens generados y tasa agregada (tokens / segundos observados).

    La tasa se calcula sobre la suma de latencias de los trabajos que
    reportaron tokens, no sobre el tiempo de pared del proceso: así no se
    diluye con períodos sin consultas.
    """
    total_tokens = sum(tokens)
    total_segundos = sum(latencias_ms) / 1000.0
    tasa = total_tokens / total_segundos if total_segundos > 0 else 0.0
    return {
        "generados": total_tokens,
        "por_segundo": round(tasa, 3),
    }
