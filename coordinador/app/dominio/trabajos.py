"""Entidad Trabajo: una consulta de un usuario y la cadena de nodos que la atiende.

`aplicar_resultado` queda separada de la entidad y del transporte (igual que
`estado_efectivo` en heartbeat.py) para poder testear la transición de
estado sin WebSocket ni repositorio.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum, auto

ROL_PRIMARIA = "primaria"
ROL_VERIFICACION = "verificacion"


class EstadoTrabajo(Enum):
    EN_COLA = auto()
    EN_CURSO = auto()
    # Verificación por réplicas activa: ya llegó UNO de los dos resultados
    # (primaria o verificación) y se está esperando el otro para comparar.
    VERIFICANDO = auto()
    COMPLETADO = auto()
    FALLIDO = auto()


ESTADOS_TERMINALES = (EstadoTrabajo.COMPLETADO, EstadoTrabajo.FALLIDO)
# Estados en los que el trabajo sigue "vivo" esperando que un nodo responda
# (a diferencia de EN_COLA, que espera que un nodo se conecte). El vigilante
# de timeout actúa sobre estos dos.
ESTADOS_ESPERANDO_NODO = (EstadoTrabajo.EN_CURSO, EstadoTrabajo.VERIFICANDO)


@dataclass(slots=True)
class Trabajo:
    trabajo_id: str
    modelo_hash: str
    usuario_id: str
    # Texto exacto que escribió el usuario. Viaja en la `asignacion` para
    # que el nodo procese esta consulta y no un prompt de demostración.
    prompt: str = ""
    cadena_nodo_ids: list[str] = field(default_factory=list)
    estado: EstadoTrabajo = EstadoTrabajo.EN_COLA
    texto_resultado: str | None = None
    error: str | None = None
    # Verificación por réplicas (opcional): si está vacía, este trabajo no
    # tiene verificación activa y se comporta exactamente como antes.
    cadena_verificacion_nodo_ids: list[str] = field(default_factory=list)
    # Resultado crudo de cada copia, (exito, texto_o_error), hasta que
    # llegan las dos y se puede comparar. None = todavía no llegó.
    resultado_primario: tuple[bool, str] | None = None
    resultado_secundario: tuple[bool, str] | None = None
    # Momento (unix) en que la primaria se despachó por el canal. Junto con
    # `latencia_ms` y `tokens_generados` alimenta `GET /metricas`.
    despachado_en_unix: float | None = None
    latencia_ms: int | None = None
    tokens_generados: int | None = None


def aplicar_resultado(trabajo: Trabajo, exito: bool, texto: str, error: str) -> Trabajo:
    """Devuelve una copia del trabajo con el resultado que reportó el nodo.

    No se aplica si el trabajo ya estaba en un estado terminal: el nodo
    puede reenviar un `resultado` (por ejemplo tras una reconexión) y no
    queremos que un mensaje tardío pise un resultado ya asentado.
    """
    if trabajo.estado in ESTADOS_TERMINALES:
        return trabajo
    if exito:
        return replace(trabajo, estado=EstadoTrabajo.COMPLETADO, texto_resultado=texto, error=None)
    return replace(trabajo, estado=EstadoTrabajo.FALLIDO, texto_resultado=None, error=error)


MENSAJE_DISCREPANCIA = "verificación por réplicas: las respuestas de los nodos no coinciden"


def aplicar_resultado_replica(trabajo: Trabajo, rol: str, exito: bool, texto: str, error: str) -> Trabajo:
    """Como `aplicar_resultado`, pero consciente de la verificación por
    réplicas: si el trabajo no tiene una cadena de verificación activa, se
    comporta exactamente igual que `aplicar_resultado` (mismo codepath para
    todos los trabajos, con o sin verificación).

    Si la verificación está activa, guarda el resultado de esta copia
    (`rol`) y, recién cuando llegaron las dos, decide: si coinciden
    (mismo éxito y mismo texto exacto), COMPLETADO con ese texto; si no
    coinciden —incluida la combinación "una falló y la otra no"—, FALLIDO
    con `MENSAJE_DISCREPANCIA`. No se intenta "elegir la más probable": una
    discrepancia es justamente la señal de que algo anda mal (un nodo
    deshonesto o roto), así que se prefiere fallar visible antes que
    devolver una respuesta que no se pudo verificar.
    """
    if trabajo.estado in ESTADOS_TERMINALES:
        return trabajo
    if not trabajo.cadena_verificacion_nodo_ids:
        return aplicar_resultado(trabajo, exito=exito, texto=texto, error=error)

    valor = (exito, texto if exito else error)
    if rol == ROL_PRIMARIA:
        actualizado = replace(trabajo, resultado_primario=valor)
    else:
        actualizado = replace(trabajo, resultado_secundario=valor)

    if actualizado.resultado_primario is None or actualizado.resultado_secundario is None:
        return replace(actualizado, estado=EstadoTrabajo.VERIFICANDO)

    coinciden = actualizado.resultado_primario == actualizado.resultado_secundario
    if coinciden and actualizado.resultado_primario[0]:
        return replace(
            actualizado,
            estado=EstadoTrabajo.COMPLETADO,
            texto_resultado=actualizado.resultado_primario[1],
            error=None,
        )
    return replace(
        actualizado, estado=EstadoTrabajo.FALLIDO, texto_resultado=None, error=MENSAJE_DISCREPANCIA
    )


MENSAJE_TIMEOUT = "timeout: el nodo no devolvió resultado a tiempo"


def marcar_despacho(trabajo: Trabajo, ahora_unix: float) -> Trabajo:
    """Registra cuándo se envió la asignación por el canal.

    Es la referencia para medir la latencia de punta a punta cuando vuelve
    el resultado. Si el trabajo ya tenía un despacho previo (reintento tras
    una desconexión) se conserva el primero: la latencia que le importa al
    usuario es desde que pidió la consulta por primera vez.
    """
    if trabajo.despachado_en_unix is not None:
        return trabajo
    return replace(trabajo, despachado_en_unix=ahora_unix)


def anotar_metricas(trabajo: Trabajo, ahora_unix: float, tokens: int = 0) -> Trabajo:
    """Anota latencia y tokens del resultado ya asentado.

    No toca el estado: se llama después de aplicar el resultado, y solo
    tiene sentido si hubo un despacho previo. `tokens` es lo que reportó el
    nodo (0 si no implementa conteo).
    """
    if trabajo.despachado_en_unix is None:
        return trabajo
    latencia_ms = max(0, int((ahora_unix - trabajo.despachado_en_unix) * 1000))
    return replace(trabajo, latencia_ms=latencia_ms, tokens_generados=max(0, tokens))


def marcar_vencido(trabajo: Trabajo) -> Trabajo:
    """Si el trabajo quedó esperando una respuesta (EN_CURSO, o
    VERIFICANDO si está esperando la segunda copia) más tiempo del
    permitido, lo marca FALLIDO.

    Solo actúa sobre esos dos estados a propósito: un trabajo EN_COLA
    (nunca se pudo despachar porque el nodo no estaba conectado) es un
    problema distinto — de cola/reintento, no de timeout — y uno ya en
    estado terminal no se toca, igual que en `aplicar_resultado`.
    """
    if trabajo.estado not in ESTADOS_ESPERANDO_NODO:
        return trabajo
    return replace(trabajo, estado=EstadoTrabajo.FALLIDO, texto_resultado=None, error=MENSAJE_TIMEOUT)


def construir_asignacion(
    trabajo: Trabajo, timeout_ms: int, *, rol: str = ROL_PRIMARIA, cadena: list[str] | None = None
) -> dict:
    """Arma el mensaje `asignacion` (formato documentado en
    `api/websockets.py`) para el primer nodo de una cadena.

    Pura a propósito: no sabe nada de WebSocket ni de si el nodo está
    conectado. La usan el despacho inicial, el reintento de cola y el
    despacho de la copia de verificación, para que el formato del mensaje
    nunca pueda divergir entre esos caminos.

    `cadena` permite construir el mensaje para la cadena de verificación
    (`trabajo.cadena_verificacion_nodo_ids`) en vez de la primaria
    (`trabajo.cadena_nodo_ids`, usada por defecto si no se pasa `cadena`).
    """
    nodos = cadena if cadena is not None else trabajo.cadena_nodo_ids
    return {
        "tipo": "asignacion",
        "trabajo_id": trabajo.trabajo_id,
        "modelo_hash": trabajo.modelo_hash,
        "prompt": trabajo.prompt,
        "posicion": 0,
        "cadena": nodos,
        "siguiente_nodo_id": nodos[1] if len(nodos) > 1 else None,
        "timeout_ms": timeout_ms,
        "rol": rol,
    }
