from __future__ import annotations

from app.dominio.trabajos import (
    MENSAJE_DISCREPANCIA,
    MENSAJE_TIMEOUT,
    ROL_PRIMARIA,
    ROL_VERIFICACION,
    EstadoTrabajo,
    Trabajo,
    anotar_metricas,
    aplicar_resultado,
    aplicar_resultado_replica,
    construir_asignacion,
    marcar_despacho,
    marcar_vencido,
)


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


def test_marcar_vencido_pasa_en_curso_a_fallido_con_mensaje_de_timeout() -> None:
    trabajo = marcar_vencido(_trabajo(EstadoTrabajo.EN_CURSO))

    assert trabajo.estado == EstadoTrabajo.FALLIDO
    assert trabajo.error == MENSAJE_TIMEOUT
    assert trabajo.texto_resultado is None


def test_marcar_vencido_no_toca_un_trabajo_en_cola() -> None:
    trabajo = _trabajo(EstadoTrabajo.EN_COLA)

    resultado = marcar_vencido(trabajo)

    assert resultado is trabajo
    assert resultado.estado == EstadoTrabajo.EN_COLA


def test_marcar_vencido_tambien_vence_verificando() -> None:
    # VERIFICANDO significa "ya llegó una de las dos copias, esperando la
    # otra" — también puede quedarse esperando para siempre.
    trabajo = marcar_vencido(_trabajo(EstadoTrabajo.VERIFICANDO))

    assert trabajo.estado == EstadoTrabajo.FALLIDO
    assert trabajo.error == MENSAJE_TIMEOUT


def test_marcar_vencido_no_pisa_un_trabajo_ya_completado() -> None:
    trabajo = _trabajo(EstadoTrabajo.COMPLETADO)
    trabajo.texto_resultado = "ya tenía resultado"

    resultado = marcar_vencido(trabajo)

    assert resultado is trabajo
    assert resultado.texto_resultado == "ya tenía resultado"


def test_marcar_vencido_no_muta_el_trabajo_original() -> None:
    original = _trabajo(EstadoTrabajo.EN_CURSO)
    marcar_vencido(original)

    assert original.estado == EstadoTrabajo.EN_CURSO
    assert original.error is None


def test_marcar_despacho_registra_el_primer_envio_y_no_lo_pisa() -> None:
    trabajo = _trabajo()

    despachado = marcar_despacho(trabajo, ahora_unix=1_000.0)
    assert despachado.despachado_en_unix == 1_000.0
    assert trabajo.despachado_en_unix is None  # no muta el original

    # Un reintento posterior conserva el primer despacho (latencia real del
    # usuario desde que pidió la consulta).
    reintentado = marcar_despacho(despachado, ahora_unix=2_000.0)
    assert reintentado.despachado_en_unix == 1_000.0


def test_anotar_metricas_calcula_latencia_y_tokens() -> None:
    trabajo = marcar_despacho(_trabajo(), ahora_unix=1_000.0)

    anotado = anotar_metricas(trabajo, ahora_unix=1_002.5, tokens=12)

    assert anotado.latencia_ms == 2_500
    assert anotado.tokens_generados == 12


def test_anotar_metricas_no_inventa_latencia_sin_despacho() -> None:
    trabajo = _trabajo()

    anotado = anotar_metricas(trabajo, ahora_unix=1_000.0, tokens=5)

    assert anotado is trabajo
    assert anotado.latencia_ms is None
    assert anotado.tokens_generados is None


def test_anotar_metricas_no_acepta_tokens_negativos() -> None:
    trabajo = marcar_despacho(_trabajo(), ahora_unix=1_000.0)

    anotado = anotar_metricas(trabajo, ahora_unix=1_001.0, tokens=-3)

    assert anotado.tokens_generados == 0


def test_construir_asignacion_con_cadena_de_varios_nodos() -> None:
    trabajo = Trabajo(
        trabajo_id="t1",
        modelo_hash="hash",
        usuario_id="u1",
        cadena_nodo_ids=["n0", "n1", "n2"],
    )

    asignacion = construir_asignacion(trabajo, timeout_ms=60_000)

    assert asignacion == {
        "tipo": "asignacion",
        "trabajo_id": "t1",
        "modelo_hash": "hash",
        "prompt": "",
        "posicion": 0,
        "cadena": ["n0", "n1", "n2"],
        "siguiente_nodo_id": "n1",
        "timeout_ms": 60_000,
        "rol": ROL_PRIMARIA,
    }


def test_construir_asignacion_con_un_solo_nodo_no_tiene_siguiente() -> None:
    trabajo = Trabajo(trabajo_id="t1", modelo_hash="hash", usuario_id="u1", cadena_nodo_ids=["n0"])

    asignacion = construir_asignacion(trabajo, timeout_ms=1_000)

    assert asignacion["siguiente_nodo_id"] is None


def test_construir_asignacion_incluye_el_prompt_de_la_consulta() -> None:
    # El nodo procesa este texto, no un prompt de demostración fijo.
    trabajo = Trabajo(
        trabajo_id="t1",
        modelo_hash="hash",
        usuario_id="u1",
        prompt="Explicá qué es un grafo dirigido",
        cadena_nodo_ids=["n0"],
    )

    asignacion = construir_asignacion(trabajo, timeout_ms=1_000)

    assert asignacion["prompt"] == "Explicá qué es un grafo dirigido"


def test_construir_asignacion_para_la_cadena_de_verificacion() -> None:
    # El trabajo guarda su cadena PRIMARIA en cadena_nodo_ids; para armar
    # el mensaje de la copia de verificación hay que pasar esa otra cadena
    # explícitamente (no vive en el trabajo bajo el mismo campo).
    trabajo = Trabajo(
        trabajo_id="t1",
        modelo_hash="hash",
        usuario_id="u1",
        cadena_nodo_ids=["n0"],
        cadena_verificacion_nodo_ids=["n1"],
    )

    asignacion = construir_asignacion(
        trabajo, timeout_ms=1_000, rol=ROL_VERIFICACION, cadena=trabajo.cadena_verificacion_nodo_ids
    )

    assert asignacion["cadena"] == ["n1"]
    assert asignacion["rol"] == ROL_VERIFICACION


def test_aplicar_resultado_replica_sin_verificacion_activa_se_comporta_como_aplicar_resultado() -> None:
    trabajo = _trabajo(EstadoTrabajo.EN_CURSO)  # cadena_verificacion_nodo_ids vacía

    resultado = aplicar_resultado_replica(trabajo, rol=ROL_PRIMARIA, exito=True, texto="hola", error="")

    assert resultado.estado == EstadoTrabajo.COMPLETADO
    assert resultado.texto_resultado == "hola"


def _trabajo_con_verificacion(estado: EstadoTrabajo = EstadoTrabajo.EN_CURSO) -> Trabajo:
    return Trabajo(
        trabajo_id="t1",
        modelo_hash="hash",
        usuario_id="u1",
        cadena_nodo_ids=["n0"],
        cadena_verificacion_nodo_ids=["n1"],
        estado=estado,
    )


def test_aplicar_resultado_replica_primera_copia_deja_verificando() -> None:
    trabajo = aplicar_resultado_replica(
        _trabajo_con_verificacion(), rol=ROL_PRIMARIA, exito=True, texto="hola", error=""
    )

    assert trabajo.estado == EstadoTrabajo.VERIFICANDO
    assert trabajo.resultado_primario == (True, "hola")
    assert trabajo.resultado_secundario is None
    # Todavía no hay veredicto: no se completa con una sola copia.
    assert trabajo.texto_resultado is None


def test_aplicar_resultado_replica_coinciden_completa_con_el_texto() -> None:
    trabajo = _trabajo_con_verificacion(EstadoTrabajo.VERIFICANDO)
    trabajo.resultado_primario = (True, "misma respuesta")

    resultado = aplicar_resultado_replica(
        trabajo, rol=ROL_VERIFICACION, exito=True, texto="misma respuesta", error=""
    )

    assert resultado.estado == EstadoTrabajo.COMPLETADO
    assert resultado.texto_resultado == "misma respuesta"
    assert resultado.error is None


def test_aplicar_resultado_replica_textos_distintos_marca_discrepancia() -> None:
    trabajo = _trabajo_con_verificacion(EstadoTrabajo.VERIFICANDO)
    trabajo.resultado_primario = (True, "respuesta A")

    resultado = aplicar_resultado_replica(
        trabajo, rol=ROL_VERIFICACION, exito=True, texto="respuesta B", error=""
    )

    assert resultado.estado == EstadoTrabajo.FALLIDO
    assert resultado.error == MENSAJE_DISCREPANCIA
    assert resultado.texto_resultado is None


def test_aplicar_resultado_replica_una_falla_y_otra_no_marca_discrepancia() -> None:
    # Una respuesta y un error nunca "coinciden", aunque tomen caminos
    # distintos: no hay forma honesta de aceptar ninguna de las dos.
    trabajo = _trabajo_con_verificacion(EstadoTrabajo.VERIFICANDO)
    trabajo.resultado_primario = (True, "respuesta válida")

    resultado = aplicar_resultado_replica(
        trabajo, rol=ROL_VERIFICACION, exito=False, texto="", error="timeout del motor"
    )

    assert resultado.estado == EstadoTrabajo.FALLIDO
    assert resultado.error == MENSAJE_DISCREPANCIA


def test_aplicar_resultado_replica_las_dos_fallan_tambien_es_discrepancia() -> None:
    # Ninguna de las dos generó un texto verificable, así que no hay nada
    # que "coincida" para aceptar — se prefiere reportarlo como
    # discrepancia explícita en vez de inventar un resultado.
    trabajo = _trabajo_con_verificacion(EstadoTrabajo.VERIFICANDO)
    trabajo.resultado_primario = (False, "error A")

    resultado = aplicar_resultado_replica(
        trabajo, rol=ROL_VERIFICACION, exito=False, texto="", error="error B"
    )

    assert resultado.estado == EstadoTrabajo.FALLIDO
    assert resultado.error == MENSAJE_DISCREPANCIA


def test_aplicar_resultado_replica_no_pisa_un_trabajo_ya_resuelto() -> None:
    trabajo = _trabajo_con_verificacion(EstadoTrabajo.COMPLETADO)
    trabajo.texto_resultado = "ya resuelto"

    resultado = aplicar_resultado_replica(
        trabajo, rol=ROL_PRIMARIA, exito=True, texto="otro texto", error=""
    )

    assert resultado is trabajo
    assert resultado.texto_resultado == "ya resuelto"


def test_aplicar_resultado_replica_no_muta_el_trabajo_original() -> None:
    original = _trabajo_con_verificacion()
    aplicar_resultado_replica(original, rol=ROL_PRIMARIA, exito=True, texto="hola", error="")

    assert original.estado == EstadoTrabajo.EN_CURSO
    assert original.resultado_primario is None
