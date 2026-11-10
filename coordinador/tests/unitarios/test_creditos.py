from __future__ import annotations

import pytest

from app.dominio.creditos import CREDITO_INICIAL_NODO_NUEVO, LibroCreditos


def test_cuenta_nueva_arranca_con_credito_inicial() -> None:
    libro = LibroCreditos()

    assert libro.saldo("cuenta-nueva") == CREDITO_INICIAL_NODO_NUEVO


def test_saldo_refleja_aportes_y_consumos() -> None:
    libro = LibroCreditos()
    libro.registrar_aporte("cuenta-1", 50.0)
    libro.registrar_consumo("cuenta-1", 20.0)

    assert libro.saldo("cuenta-1") == pytest.approx(CREDITO_INICIAL_NODO_NUEVO + 30.0)


def test_ratio_sin_consumo_previo_es_maximo() -> None:
    libro = LibroCreditos()
    libro.registrar_aporte("cuenta-1", 10.0)

    assert libro.ratio("cuenta-1") == float("inf")


def test_ratio_calcula_aporte_sobre_consumo() -> None:
    libro = LibroCreditos()
    libro.registrar_aporte("cuenta-1", 40.0)
    libro.registrar_consumo("cuenta-1", 10.0)

    assert libro.ratio("cuenta-1") == pytest.approx(4.0)


@pytest.mark.parametrize("monto", [0, -5])
def test_rechaza_montos_no_positivos(monto: float) -> None:
    libro = LibroCreditos()

    with pytest.raises(ValueError):
        libro.registrar_aporte("cuenta-1", monto)
