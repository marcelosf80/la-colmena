from __future__ import annotations

from app.dominio.trabajos import EstadoTrabajo, Trabajo, aplicar_resultado


def _trabajo(estado: EstadoTrabajo = EstadoTrabajo.EN_CURSO) -> Trabajo:
    return Trabajo(
        trabajo_id="t1",
        modelo_hash="hash",
        usuario_id="u1",
        cadena_nodo_ids=["n0"],
        estado=estado,
    )


def test_resultado_exitoso_marca_completado_y_guarda_el_texto() -> None:
    trabajo = aplicar_resultado(_trabajo(), exito=True, texto="hola", error="")

    assert trabajo.estado == EstadoTrabajo.COMPLETADO
    assert trabajo.texto_resultado == "hola"
    assert trabajo.error is None


def test_resultado_fallido_marca_fallido_y_guarda_el_error() -> None:
    trabajo = aplicar_resultado(_trabajo(), exito=False, texto="", error="timeout del motor")

    assert trabajo.estado == EstadoTrabajo.FALLIDO
    assert trabajo.texto_resultado is None
    assert trabajo.error == "timeout del motor"


def test_no_pisa_un_trabajo_ya_completado() -> None:
    trabajo = _trabajo(EstadoTrabajo.COMPLETADO)
    trabajo.texto_resultado = "resultado original"

    resultado = aplicar_resultado(trabajo, exito=True, texto="otro texto", error="")

    assert resultado is trabajo
    assert resultado.texto_resultado == "resultado original"


def test_no_pisa_un_trabajo_ya_fallido() -> None:
    trabajo = _trabajo(EstadoTrabajo.FALLIDO)
    trabajo.error = "error original"

    resultado = aplicar_resultado(trabajo, exito=False, texto="", error="otro error")

    assert resultado is trabajo
    assert resultado.error == "error original"


def test_no_muta_el_trabajo_original() -> None:
    original = _trabajo()
    aplicar_resultado(original, exito=True, texto="hola", error="")

    assert original.estado == EstadoTrabajo.EN_CURSO
    assert original.texto_resultado is None
