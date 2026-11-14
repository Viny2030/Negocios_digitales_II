"""
Copia el histórico de `channel_analytics.db` (SQLite) a PostgreSQL sin pérdida de datos.

Por defecto es un ENSAYO: valida y cuenta, no escribe nada. Con --aplicar copia todo en
UNA sola transacción del destino (si algo falla, el destino queda como estaba).

    python -m scripts.migrar_sqlite_a_postgres `
        --origen "sqlite+aiosqlite:///./channel_analytics.db" `
        --destino "postgresql+asyncpg://analytics:analytics@localhost:5432/channel_analytics"

    (agregar --aplicar cuando el ensayo salga limpio)

Qué hace, en orden:
  1. Lee las tablas y columnas desde `app.db.models.Base.metadata` (la misma fuente que usa
     `init_db`), así una columna nueva del modelo se migra sin tocar este script.
  2. Valida el origen contra las diferencias reales entre SQLite y Postgres:
       - SQLite no hace cumplir VARCHAR(n): un texto más largo que la columna se rechaza acá,
         antes de que Postgres corte la transacción a mitad de camino;
       - columnas NOT NULL sin default que no existan en una base SQLite vieja;
       - duplicados en las claves UNIQUE (SQLite no las tenía si la tabla es anterior al modelo).
  3. Exige que las tablas del destino estén vacías: así no se mezcla un histórico con otro
     ni se pisan los tipos de canal que `init_db` siembra en una base recién creada.
  4. Crea las tablas que falten (`create_all`), copia en orden de claves foráneas y en lotes,
     conservando los `id` (los snapshots siguen apuntando a su canal).
  5. Reubica las secuencias de los `id` con `setval`, para que el próximo INSERT no choque.
  6. Verifica: misma cantidad de filas por tabla y mismas sumas de las métricas BIGINT.

Hacer un respaldo antes: copiar el archivo .db alcanza
(PowerShell: Copy-Item channel_analytics.db channel_analytics.backup.db). Se recomienda arrancar la app una vez contra el SQLite antes
de migrar, para que las migraciones livianas de `app/db/session.py` agreguen columnas nuevas.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field

from sqlalchemy import BigInteger, String, Table, func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.db.models import Base

BATCH_SIZE = 1_000


@dataclass
class Informe:
    filas_origen: dict[str, int] = field(default_factory=dict)
    columnas_faltantes: dict[str, list[str]] = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)


def _tablas() -> list[Table]:
    """Tablas del modelo, padres antes que hijas (orden de claves foráneas)."""
    return list(Base.metadata.sorted_tables)


async def _columnas_existentes(conn: AsyncConnection, tabla: str) -> set[str] | None:
    def _leer(sync_conn) -> set[str] | None:
        insp = inspect(sync_conn)
        if not insp.has_table(tabla):
            return None
        return {c["name"] for c in insp.get_columns(tabla)}

    return await conn.run_sync(_leer)


async def validar_origen(conn: AsyncConnection) -> tuple[Informe, dict[str, list[str]]]:
    informe = Informe()
    columnas_a_copiar: dict[str, list[str]] = {}

    for tabla in _tablas():
        existentes = await _columnas_existentes(conn, tabla.name)
        if existentes is None:
            informe.filas_origen[tabla.name] = 0
            columnas_a_copiar[tabla.name] = []
            continue

        comunes = [c.name for c in tabla.columns if c.name in existentes]
        faltantes = [c.name for c in tabla.columns if c.name not in existentes]
        columnas_a_copiar[tabla.name] = comunes
        if faltantes:
            informe.columnas_faltantes[tabla.name] = faltantes
            for nombre in faltantes:
                col = tabla.c[nombre]
                if (
                    not col.nullable
                    and col.default is None
                    and col.server_default is None
                    and not col.primary_key
                ):
                    informe.errores.append(
                        f"{tabla.name}.{nombre}: es NOT NULL sin default y no existe en el origen. "
                        "Arrancá la app una vez contra el SQLite para que session.py la agregue."
                    )

        total = (
            await conn.execute(select(func.count()).select_from(tabla))
        ).scalar_one()
        informe.filas_origen[tabla.name] = total

        # VARCHAR(n): SQLite acepta cualquier largo, Postgres no.
        for col in tabla.columns:
            if col.name in comunes and isinstance(col.type, String) and col.type.length:
                maximo = (
                    await conn.execute(select(func.max(func.length(col))))
                ).scalar()
                if maximo and maximo > col.type.length:
                    informe.errores.append(
                        f"{tabla.name}.{col.name}: hay textos de {maximo} caracteres y la columna admite "
                        f"{col.type.length}. Recortalos o ampliá la columna antes de migrar."
                    )

        # UNIQUE: una tabla SQLite creada antes de agregar la restricción puede tener duplicados.
        for restriccion in tabla.constraints:
            columnas = [c.name for c in getattr(restriccion, "columns", [])]
            es_unique = restriccion.__class__.__name__ == "UniqueConstraint"
            if es_unique and columnas and all(c in comunes for c in columnas):
                cols = [tabla.c[c] for c in columnas]
                dup = (
                    await conn.execute(
                        select(*cols).group_by(*cols).having(func.count() > 1).limit(1)
                    )
                ).first()
                if dup is not None:
                    informe.errores.append(
                        f"{tabla.name}: valores duplicados en UNIQUE {columnas}: {tuple(dup)}"
                    )
        for col in tabla.columns:
            if col.unique and col.name in comunes:
                dup = (
                    await conn.execute(
                        select(col).group_by(col).having(func.count() > 1).limit(1)
                    )
                ).first()
                if dup is not None:
                    informe.errores.append(
                        f"{tabla.name}.{col.name}: valor duplicado en columna UNIQUE: {dup[0]!r}"
                    )

    return informe, columnas_a_copiar


async def _sumas_bigint(conn: AsyncConnection) -> dict[str, int]:
    sumas: dict[str, int] = {}
    for tabla in _tablas():
        if await _columnas_existentes(conn, tabla.name) is None:
            continue
        for col in tabla.columns:
            if isinstance(col.type, BigInteger):
                valor = (
                    await conn.execute(select(func.coalesce(func.sum(col), 0)))
                ).scalar_one()
                sumas[f"{tabla.name}.{col.name}"] = int(valor)
    return sumas


async def _destino_vacio(conn: AsyncConnection) -> list[str]:
    ocupadas = []
    for tabla in _tablas():
        if await _columnas_existentes(conn, tabla.name) is None:
            continue
        if (await conn.execute(select(func.count()).select_from(tabla))).scalar_one():
            ocupadas.append(tabla.name)
    return ocupadas


async def _reubicar_secuencias(conn: AsyncConnection) -> None:
    if conn.dialect.name != "postgresql":
        return
    for tabla in _tablas():
        pk = list(tabla.primary_key.columns)
        if len(pk) != 1 or not pk[0].autoincrement or pk[0].type.python_type is not int:
            continue
        nombre, col = tabla.name, pk[0].name
        await conn.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{nombre}', '{col}'), "
                f"COALESCE((SELECT MAX({col}) FROM {nombre}), 1), "
                f"(SELECT MAX({col}) IS NOT NULL FROM {nombre}))"
            )
        )


async def migrar(origen_url: str, destino_url: str, aplicar: bool) -> int:
    origen = create_async_engine(origen_url)
    destino = create_async_engine(destino_url)
    try:
        async with origen.connect() as src:
            informe, columnas = await validar_origen(src)
            sumas_origen = await _sumas_bigint(src)

        print("Filas en el origen:")
        for nombre, total in informe.filas_origen.items():
            print(f"  {nombre:<28} {total:>10}")
        for nombre, faltan in informe.columnas_faltantes.items():
            print(
                f"  aviso: {nombre} no tiene {faltan} en el origen; quedan con su default o NULL"
            )

        async with destino.connect() as dst:
            ocupadas = await _destino_vacio(dst)
        if ocupadas:
            informe.errores.append(
                f"El destino ya tiene datos en {ocupadas}. Usá una base vacía: si la app ya arrancó contra "
                "ella, init_db sembró channel_types; borrá esas filas o recreá la base."
            )

        if informe.errores:
            print("\nNo se puede migrar todavía:")
            for err in informe.errores:
                print(f"  - {err}")
            return 1

        if not aplicar:
            print("\nEnsayo limpio. Repetí con --aplicar para copiar los datos.")
            return 0

        async with destino.begin() as dst:  # una sola transacción: todo o nada
            await dst.run_sync(Base.metadata.create_all)
            async with origen.connect() as src:
                for tabla in _tablas():
                    cols = columnas[tabla.name]
                    if not cols:
                        continue
                    pk = list(tabla.primary_key.columns)
                    consulta = select(*[tabla.c[c] for c in cols]).order_by(*pk)
                    resultado = await src.stream(consulta)
                    async for lote in resultado.partitions(BATCH_SIZE):
                        await dst.execute(
                            tabla.insert(), [dict(fila._mapping) for fila in lote]
                        )
            await _reubicar_secuencias(dst)

        async with destino.connect() as dst:
            filas_destino = {
                t.name: (
                    await dst.execute(select(func.count()).select_from(t))
                ).scalar_one()
                for t in _tablas()
            }
            sumas_destino = await _sumas_bigint(dst)

        diferencias = [
            f"{nombre}: origen {informe.filas_origen[nombre]} / destino {filas_destino[nombre]}"
            for nombre in filas_destino
            if filas_destino[nombre] != informe.filas_origen.get(nombre, 0)
        ]
        diferencias += [
            f"suma {clave}: origen {valor} / destino {sumas_destino.get(clave)}"
            for clave, valor in sumas_origen.items()
            if sumas_destino.get(clave) != valor
        ]
        if diferencias:
            print("\nLa verificación encontró diferencias:")
            for d in diferencias:
                print(f"  - {d}")
            return 2

        print(
            "\nMigración verificada: mismas filas por tabla y mismas sumas de métricas."
        )
        return 0
    finally:
        await origen.dispose()
        await destino.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--origen", default="sqlite+aiosqlite:///./channel_analytics.db"
    )
    parser.add_argument(
        "--destino",
        required=True,
        help="postgresql+asyncpg://usuario:clave@host:5432/base",
    )
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="copiar de verdad (sin esto es un ensayo)",
    )
    args = parser.parse_args(argv)
    destino = args.destino
    for prefijo in ("postgres://", "postgresql://"):
        if destino.startswith(
            prefijo
        ):  # mismo ajuste que Settings._normalize_database_url
            destino = "postgresql+asyncpg://" + destino[len(prefijo) :]
    return asyncio.run(migrar(args.origen, destino, args.aplicar))


if __name__ == "__main__":
    sys.exit(main())
