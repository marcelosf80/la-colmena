"""Libro mayor de créditos: append-only, nunca se modifican asientos existentes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

CREDITO_INICIAL_NODO_NUEVO = 10.0


class TipoAsiento(Enum):
    APORTE = auto()  # cómputo verificado donado
    CONSUMO = auto()  # consulta realizada


@dataclass(frozen=True, slots=True)
class Asiento:
    cuenta_id: str
    tipo: TipoAsiento
    monto: float


@dataclass(slots=True)
class LibroCreditos:
    asientos: list[Asiento] = field(default_factory=list)

    def registrar_aporte(self, cuenta_id: str, monto: float) -> None:
        if monto <= 0:
            raise ValueError("El monto de un aporte debe ser positivo")
        self.asientos.append(Asiento(cuenta_id, TipoAsiento.APORTE, monto))

    def registrar_consumo(self, cuenta_id: str, monto: float) -> None:
        if monto <= 0:
            raise ValueError("El monto de un consumo debe ser positivo")
        self.asientos.append(Asiento(cuenta_id, TipoAsiento.CONSUMO, monto))

    def saldo(self, cuenta_id: str) -> float:
        """El crédito inicial es un punto de partida permanente para toda
        cuenta nueva, no algo que se pierde apenas hay movimientos.
        """
        aportes = sum(
            a.monto for a in self.asientos if a.cuenta_id == cuenta_id and a.tipo == TipoAsiento.APORTE
        )
        consumos = sum(
            a.monto for a in self.asientos if a.cuenta_id == cuenta_id and a.tipo == TipoAsiento.CONSUMO
        )
        return CREDITO_INICIAL_NODO_NUEVO + aportes - consumos

    def ratio(self, cuenta_id: str) -> float:
        """Aporte sobre consumo. Un ratio alto da prioridad de cola.
        Cuentas sin consumo todavía devuelven infinito (máxima prioridad).
        """
        aportes = sum(
            a.monto for a in self.asientos if a.cuenta_id == cuenta_id and a.tipo == TipoAsiento.APORTE
        )
        consumos = sum(
            a.monto for a in self.asientos if a.cuenta_id == cuenta_id and a.tipo == TipoAsiento.CONSUMO
        )
        if consumos == 0:
            return float("inf") if aportes > 0 else 1.0
        return aportes / consumos
