#!/usr/bin/env python3
"""One-time copy of an existing HaploSearch SQL Server database into SQLite.

Copies every relational table (keeping IDs) and converts the legacy ``.npz``
lookup artifacts into ``presence_bitmaps`` rows inside the SQLite file, so the
result is a single self-contained database.

Requires pyodbc and an ODBC driver, which are no longer app dependencies:

    pip install pyodbc
    python scripts/migrate_mssql_to_sqlite.py \\
        --mssql-connection-string "DRIVER={ODBC Driver 18 for SQL Server};SERVER=...;..." \\
        --artifact-dir /srv/hapsearch/production/presence_artifacts \\
        --output data/hapsearch.db
"""

import argparse
import datetime
import os
import sqlite3
import sys
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from database.db_manager import DatabaseManager  # noqa: E402
from database.presence_artifacts import (  # noqa: E402
    ARTIFACT_SCHEMA_VERSION,
    DEFAULT_COMPRESSION,
)
from scripts.init_database import init_database  # noqa: E402

# Parent tables first so IDs referenced by later tables already exist.
TABLES = [
    "species",
    "chromosomes",
    "markers",
    "microhaplotypes",
    "variants",
    "botloci",
    "projects",
    "samples",
    "microhaplotype_samples",
    "contacts",
    "project_contacts",
    "users",
]

LEGACY_LOOKUP_TYPES = {"sample_lookup": "sample", "project_lookup": "project"}


def _to_sqlite_value(value):
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if hasattr(value, "as_integer_ratio") and not isinstance(value, (int, float)):
        return float(value)  # Decimal
    return value


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _mssql_rows(mssql_cursor, query: str) -> Tuple[List[str], List[Sequence]]:
    mssql_cursor.execute(query)
    columns = [column[0] for column in mssql_cursor.description]
    return columns, mssql_cursor.fetchall()


def _mssql_table_exists(mssql_cursor, table: str) -> bool:
    mssql_cursor.execute("SELECT OBJECT_ID(?, 'U')", (f"dbo.{table}",))
    row = mssql_cursor.fetchone()
    return bool(row and row[0] is not None)


def copy_table(mssql_cursor, sqlite_conn: sqlite3.Connection, table: str) -> int:
    """Copy one table, keeping only columns that exist in both schemas."""
    if not _mssql_table_exists(mssql_cursor, table):
        print(f"  {table}: not in SQL Server, skipped")
        return 0

    source_columns, rows = _mssql_rows(mssql_cursor, f"SELECT * FROM [{table}]")
    target_columns = set(_sqlite_columns(sqlite_conn, table))
    columns = [column for column in source_columns if column in target_columns]
    indexes = [source_columns.index(column) for column in columns]

    placeholders = ",".join(["?"] * len(columns))
    column_list = ",".join(f'"{column}"' for column in columns)
    sqlite_conn.executemany(
        f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders})',
        ([_to_sqlite_value(row[i]) for i in indexes] for row in rows),
    )
    print(f"  {table}: {len(rows):,} rows")
    return len(rows)


def _resolve_artifact_path(artifact_path: str, artifact_dir: Optional[str]) -> Optional[str]:
    candidates = [artifact_path]
    if artifact_dir:
        candidates.append(os.path.join(artifact_dir, os.path.basename(artifact_path)))
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def convert_artifacts(
    mssql_cursor,
    sqlite_conn: sqlite3.Connection,
    artifact_dir: Optional[str],
) -> Dict[int, int]:
    """Convert legacy lookup .npz files into SQLite bitmap rows.

    Returns a map from legacy artifact IDs (both the lookup file and its
    microhaplotype-oriented sibling) to the new artifact ID, so summary rows
    can keep pointing at the matrix they were computed from.
    """
    if not _mssql_table_exists(mssql_cursor, "presence_artifacts"):
        print("  presence_artifacts: not in SQL Server, skipped")
        return {}

    columns, rows = _mssql_rows(
        mssql_cursor,
        "SELECT * FROM presence_artifacts ORDER BY created_at, id",
    )
    legacy = [dict(zip(columns, row)) for row in rows]
    id_map: Dict[int, int] = {}
    missing: List[str] = []

    for record in legacy:
        entity_type = LEGACY_LOOKUP_TYPES.get(record["entity_type"])
        if entity_type is None:
            continue
        path = _resolve_artifact_path(record["artifact_path"], artifact_dir)
        if path is None:
            missing.append(record["artifact_path"])
            continue

        with np.load(path, allow_pickle=False) as data:
            entity_ids = data["entity_ids"].astype(np.int64)
            microhaplotype_ids = data["microhaplotype_ids"].astype(np.int64)
            packed_presence = data["packed_presence"].astype(np.uint8)
            microhaplotype_count = int(data["microhaplotype_count"][0])
        present_counts = np.unpackbits(
            packed_presence, axis=1, bitorder="little"
        )[:, :microhaplotype_count].sum(axis=1)

        cursor = sqlite_conn.execute(
            """
            INSERT INTO presence_artifacts
            (entity_type, species_id, project_id, source_path, source_sha256,
             compression, schema_version, microhaplotype_count, entity_count,
             presence_count, artifact_size_bytes, microhaplotype_ids, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_type,
                record.get("species_id"),
                record.get("project_id"),
                record["source_path"],
                record.get("source_sha256"),
                DEFAULT_COMPRESSION,
                ARTIFACT_SCHEMA_VERSION,
                microhaplotype_count,
                len(entity_ids),
                int(present_counts.sum()),
                int(packed_presence.nbytes + microhaplotype_ids.nbytes),
                microhaplotype_ids.astype("<i8").tobytes(),
                _to_sqlite_value(record["created_at"]),
            ),
        )
        new_id = int(cursor.lastrowid)
        sqlite_conn.executemany(
            """
            INSERT INTO presence_bitmaps
            (artifact_id, row_index, entity_id, present_count, packed_presence)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    new_id,
                    row_index,
                    int(entity_ids[row_index]),
                    int(present_counts[row_index]),
                    packed_presence[row_index].tobytes(),
                )
                for row_index in range(len(entity_ids))
            ],
        )
        id_map[int(record["id"])] = new_id

        # Each lookup file was written next to a microhaplotype-oriented copy
        # of the same matrix; summary rows reference that sibling's ID.
        siblings = [
            other for other in legacy
            if other["entity_type"] == entity_type
            and other["source_path"] == record["source_path"]
            and other.get("project_id") == record.get("project_id")
        ]
        if siblings:
            nearest = min(
                siblings,
                key=lambda other: abs(
                    (other["created_at"] - record["created_at"]).total_seconds()
                ),
            )
            id_map[int(nearest["id"])] = new_id

        print(
            f"  {entity_type} artifact {record['id']} -> {new_id}: "
            f"{len(entity_ids):,} x {microhaplotype_count:,}"
        )

    if missing:
        print(f"  Warning: {len(missing)} artifact files not found:")
        for path in missing:
            print(f"    {path}")
    return id_map


def copy_presence_summary(
    mssql_cursor,
    sqlite_conn: sqlite3.Connection,
    artifact_id_map: Dict[int, int],
) -> int:
    table = "microhaplotype_presence_summary"
    if not _mssql_table_exists(mssql_cursor, table):
        return 0
    columns, rows = _mssql_rows(
        mssql_cursor,
        f"SELECT microhaplotype_id, species_id, entity_type, present_count, "
        f"total_count, frequency, artifact_id, updated_at FROM {table}",
    )
    sqlite_conn.executemany(
        f"""
        INSERT INTO {table}
        (microhaplotype_id, species_id, entity_type, present_count,
         total_count, frequency, artifact_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                row[0], row[1], row[2], row[3], row[4], float(row[5]),
                artifact_id_map.get(row[6]) if row[6] is not None else None,
                _to_sqlite_value(row[7]),
            )
            for row in rows
        ),
    )
    print(f"  {table}: {len(rows):,} rows")
    return len(rows)


def migrate(connection_string: str, output_path: str, artifact_dir: Optional[str]) -> bool:
    try:
        import pyodbc
    except ImportError:
        print("Error: pyodbc is required for the migration. Install it with: pip install pyodbc")
        return False

    if not init_database(force=True, db_path=output_path):
        return False

    print("\nConnecting to SQL Server...")
    mssql_conn = pyodbc.connect(connection_string)
    sqlite_conn = sqlite3.connect(output_path)
    try:
        sqlite_conn.execute("PRAGMA foreign_keys = OFF")
        mssql_cursor = mssql_conn.cursor()

        print("\nCopying tables:")
        for table in TABLES:
            copy_table(mssql_cursor, sqlite_conn, table)

        print("\nConverting presence artifacts:")
        artifact_id_map = convert_artifacts(mssql_cursor, sqlite_conn, artifact_dir)
        copy_presence_summary(mssql_cursor, sqlite_conn, artifact_id_map)
        sqlite_conn.commit()

        problems = sqlite_conn.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            print(f"\nWarning: {len(problems)} foreign key violations (first 10):")
            for problem in problems[:10]:
                print(f"  {problem}")

    finally:
        sqlite_conn.close()
        mssql_conn.close()

    print("\nOptimizing database file...")
    DatabaseManager(db_path=output_path, read_only=False).optimize(vacuum=True)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"\nMigration complete: {output_path} ({size_mb:.1f} MB)")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--mssql-connection-string",
        default=os.getenv("MSSQL_CONNECTION_STRING"),
        help="ODBC connection string for the source SQL Server (or MSSQL_CONNECTION_STRING)",
    )
    parser.add_argument(
        "--artifact-dir",
        help="Directory holding the legacy .npz artifacts, if they moved since import",
    )
    parser.add_argument(
        "--output",
        default=config.SQLITE_DB_PATH,
        help="SQLite file to create (replaced if it exists)",
    )
    args = parser.parse_args()

    if not args.mssql_connection_string:
        parser.error("--mssql-connection-string or MSSQL_CONNECTION_STRING is required")

    sys.exit(0 if migrate(args.mssql_connection_string, args.output, args.artifact_dir) else 1)


if __name__ == "__main__":
    main()
