"""Repositorios Postgres con asyncpg.

Mismo contrato async que las implementaciones en memoria. El esquema se
crea idempotente en el arranque (CREATE TABLE IF NOT EXISTS); las
migraciones formales (alembic) quedan pendientes para cuando el esquema
deje de ser estable.
"""

from __future__ import annotations

from typing import cast

import asyncpg

from app.dominio.creditos import TipoAsiento
from app.dominio.nodos import Candidato, EstadoNodo, Nodo
from app.dominio.trabajos import EstadoTrabajo, Trabajo

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodos (
    nodo_id TEXT PRIMARY KEY,
    ram_donada_mb BIGINT NOT NULL,
    cores_donados INTEGER NOT NULL,
    tiene_gpu BOOLEAN NOT NULL,
    tokens_por_segundo DOUBLE PRECISION NOT NULL,
    estado TEXT NOT NULL
);
-- Columna agregada después del esquema inicial: ALTER idempotente para
-- bases ya creadas (no hay migraciones versionadas todavía).
ALTER TABLE nodos ADD COLUMN IF NOT EXISTS ultimo_latido TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS candidatos (
    modelo_hash TEXT NOT NULL,
    posicion INTEGER NOT NULL,
    nodo_id TEXT NOT NULL REFERENCES nodos (nodo_id) ON DELETE CASCADE,
    consultas_en_curso INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (modelo_hash, posicion, nodo_id)
);

CREATE TABLE IF NOT EXISTS asientos_creditos (
    id BIGSERIAL PRIMARY KEY,
    cuenta_id TEXT NOT NULL,
    tipo TEXT NOT NULL,
    monto DOUBLE PRECISION NOT NULL CHECK (monto > 0),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_asientos_cuenta ON asientos_creditos (cuenta_id);

CREATE TABLE IF NOT EXISTS trabajos (
    trabajo_id UUID PRIMARY KEY,
    usuario_id TEXT NOT NULL,
    modelo_hash TEXT NOT NULL,
    cadena_nodo_ids TEXT[] NOT NULL DEFAULT '{}',
    estado TEXT NOT NULL,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trabajos_usuario ON trabajos (usuario_id);
-- Columnas agregadas cuando se sumó el resultado de vuelta por WebSocket.
ALTER TABLE trabajos ADD COLUMN IF NOT EXISTS texto_resultado TEXT;
ALTER TABLE trabajos ADD COLUMN IF NOT EXISTS error TEXT;
"""


async def crear_esquema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conexion:
        await conexion.execute(ESQUEMA_SQL)


async def armar_pool(bd_url: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(bd_url)
    await crear_esquema(pool)
    return pool


class RepositorioCandidatosPostgres:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def registrar(self, candidato: Candidato) -> None:
        async with self._pool.acquire() as conexion:
            async with conexion.transaction():
                await conexion.execute(
                    """
                    INSERT INTO nodos
                        (nodo_id, ram_donada_mb, cores_donados, tiene_gpu,
                         tokens_por_segundo, estado, ultimo_latido)
                    VALUES ($1, $2, $3, $4, $5, $6, now())
                    ON CONFLICT (nodo_id) DO UPDATE SET
                        ram_donada_mb = EXCLUDED.ram_donada_mb,
                        cores_donados = EXCLUDED.cores_donados,
                        tiene_gpu = EXCLUDED.tiene_gpu,
                        tokens_por_segundo = EXCLUDED.tokens_por_segundo,
                        estado = EXCLUDED.estado,
                        ultimo_latido = now()
                    """,
                    candidato.nodo.nodo_id,
                    candidato.nodo.ram_donada_mb,
                    candidato.nodo.cores_donados,
                    candidato.nodo.tiene_gpu,
                    candidato.nodo.tokens_por_segundo,
                    candidato.nodo.estado.name,
                )
                await conexion.execute(
                    """
                    INSERT INTO candidatos
                        (modelo_hash, posicion, nodo_id, consultas_en_curso)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (modelo_hash, posicion, nodo_id)
                        DO UPDATE SET consultas_en_curso = EXCLUDED.consultas_en_curso
                    """,
                    candidato.modelo_hash,
                    candidato.posicion,
                    candidato.nodo.nodo_id,
                    candidato.consultas_en_curso,
                )

    async def listar_por_modelo(self, modelo_hash: str) -> list[Candidato]:
        filas = await self._pool.fetch(
            """
            SELECT c.modelo_hash, c.posicion, c.consultas_en_curso,
                   n.nodo_id, n.ram_donada_mb, n.cores_donados,
                   n.tiene_gpu, n.tokens_por_segundo, n.estado
              FROM candidatos c
              JOIN nodos n ON n.nodo_id = c.nodo_id
             WHERE c.modelo_hash = $1
            """,
            modelo_hash,
        )
        return [_fila_a_candidato(fila) for fila in filas]

    async def listar_todos(self) -> list[Candidato]:
        filas = await self._pool.fetch(
            """
            SELECT c.modelo_hash, c.posicion, c.consultas_en_curso,
                   n.nodo_id, n.ram_donada_mb, n.cores_donados,
                   n.tiene_gpu, n.tokens_por_segundo, n.estado
              FROM candidatos c
              JOIN nodos n ON n.nodo_id = c.nodo_id
            """
        )
        return [_fila_a_candidato(fila) for fila in filas]

    async def actualizar_latido(
        self,
        nodo_id: str,
        estado: EstadoNodo,
        consultas_en_curso: int,
        momento_unix: float,
    ) -> bool:
        async with self._pool.acquire() as conexion:
            async with conexion.transaction():
                resultado = await conexion.execute(
                    """
                    UPDATE nodos
                       SET estado = $2, ultimo_latido = to_timestamp($3::double precision)
                     WHERE nodo_id = $1
                    """,
                    nodo_id,
                    estado.name,
                    momento_unix,
                )
                if resultado == "UPDATE 0":
                    return False
                await conexion.execute(
                    "UPDATE candidatos SET consultas_en_curso = $2 WHERE nodo_id = $1",
                    nodo_id,
                    consultas_en_curso,
                )
                return True

    async def marcar_caidos_sin_latido(
        self, ahora_unix: float, timeout_s: float
    ) -> list[str]:
        filas = await self._pool.fetch(
            """
            UPDATE nodos
               SET estado = 'CAIDO', ultimo_latido = to_timestamp($1::double precision)
             WHERE estado <> 'CAIDO'
               AND (ultimo_latido IS NULL
                    OR ultimo_latido < to_timestamp($1::double precision - $2::double precision))
            RETURNING nodo_id
            """,
            ahora_unix,
            timeout_s,
        )
        return [fila["nodo_id"] for fila in filas]


def _fila_a_candidato(fila: asyncpg.Record) -> Candidato:
    nodo = Nodo(
        nodo_id=fila["nodo_id"],
        ram_donada_mb=fila["ram_donada_mb"],
        cores_donados=fila["cores_donados"],
        tiene_gpu=fila["tiene_gpu"],
        tokens_por_segundo=fila["tokens_por_segundo"],
        estado=cast(EstadoNodo, EstadoNodo[fila["estado"]]),
    )
    return Candidato(
        modelo_hash=fila["modelo_hash"],
        posicion=fila["posicion"],
        nodo=nodo,
        consultas_en_curso=fila["consultas_en_curso"],
    )


class RepositorioTrabajosPostgres:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def guardar(self, trabajo: Trabajo) -> None:
        await self._pool.execute(
            """
            INSERT INTO trabajos
                (trabajo_id, usuario_id, modelo_hash, cadena_nodo_ids, estado,
                 texto_resultado, error)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (trabajo_id) DO UPDATE SET
                estado = EXCLUDED.estado,
                cadena_nodo_ids = EXCLUDED.cadena_nodo_ids,
                texto_resultado = EXCLUDED.texto_resultado,
                error = EXCLUDED.error
            """,
            trabajo.trabajo_id,
            trabajo.usuario_id,
            trabajo.modelo_hash,
            trabajo.cadena_nodo_ids,
            trabajo.estado.name,
            trabajo.texto_resultado,
            trabajo.error,
        )

    async def obtener(self, trabajo_id: str) -> Trabajo | None:
        fila = await self._pool.fetchrow(
            """
            SELECT trabajo_id, usuario_id, modelo_hash, cadena_nodo_ids, estado,
                   texto_resultado, error
              FROM trabajos
             WHERE trabajo_id = $1::uuid
            """,
            trabajo_id,
        )
        if fila is None:
            return None
        return Trabajo(
            trabajo_id=str(fila["trabajo_id"]),
            usuario_id=fila["usuario_id"],
            modelo_hash=fila["modelo_hash"],
            cadena_nodo_ids=list(fila["cadena_nodo_ids"]),
            estado=cast(EstadoTrabajo, EstadoTrabajo[fila["estado"]]),
            texto_resultado=fila["texto_resultado"],
            error=fila["error"],
        )


class RepositorioCreditosPostgres:
    """Append-only: nunca se modifica un asiento existente, solo se acumula."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def registrar_asiento(
        self, cuenta_id: str, tipo: TipoAsiento, monto: float
    ) -> None:
        if monto <= 0:
            raise ValueError("El monto de un asiento debe ser positivo")
        await self._pool.execute(
            "INSERT INTO asientos_creditos (cuenta_id, tipo, monto) VALUES ($1, $2, $3)",
            cuenta_id,
            tipo.name,
            monto,
        )

    async def saldos(self, cuenta_id: str) -> tuple[float, float]:
        fila = await self._pool.fetchrow(
            """
            SELECT
                COALESCE(SUM(monto) FILTER (WHERE tipo = 'APORTE'), 0) AS aportes,
                COALESCE(SUM(monto) FILTER (WHERE tipo = 'CONSUMO'), 0) AS consumos
              FROM asientos_creditos
             WHERE cuenta_id = $1
            """,
            cuenta_id,
        )
        assert fila is not None
        return float(fila["aportes"]), float(fila["consumos"])
