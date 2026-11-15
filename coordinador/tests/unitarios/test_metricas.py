from __future__ import annotations

from app.dominio.metricas import percentil, resumen_latencias, resumen_tokens


def test_percentil_vacio_devuelve_none() -> None:
    assert percentil([], 50) is None


def test_percentil_ignora_p_fuera_de_rango() -> None:
    assert percentil([1, 2, 3], -1) is None
    assert percentil([1, 2, 3], 101) is None


def test_percentil_devuelve_valores_observados() -> None:
    valores = [10, 20, 30, 40, 50]

    assert percentil(valores, 50) == 30
    assert percentil(valores, 0) == 10
    assert percentil(valores, 100) == 50
    # p95 con muestra chica cae en el máximo observado, no interpola.
    assert percentil(valores, 95) == 50


def test_percentil_no_depende_del_orden_de_entrada() -> None:
    assert percentil([300, 100, 200], 50) == 200


def test_resumen_latencias_incluye_p50_p95_y_muestra() -> None:
    resumen = resumen_latencias([100, 200, 300, 400])

    assert resumen["p50"] == 300  # índice redondeado sobre 4 elementos
    assert resumen["p95"] == 400
    assert resumen["muestra"] == 4


def test_resumen_tokens_calcula_tasa_sobre_latencias_observadas() -> None:
    # 30 tokens en 3 segundos observados = 10 tokens/s.
    resumen = resumen_tokens([10, 20], [1_000, 2_000])

    assert resumen["generados"] == 30
    assert resumen["por_segundo"] == 10.0


def test_resumen_tokens_sin_muestra_no_divide_por_cero() -> None:
    assert resumen_tokens([], []) == {"generados": 0, "por_segundo": 0.0}
