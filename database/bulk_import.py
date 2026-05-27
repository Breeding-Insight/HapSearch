"""Bulk import helpers for Microsoft SQL Server presence data.

Uses a staging-table pattern to minimize transaction log pressure:
  1. Load (microhaplotype_id, entity_id) pairs into a temp heap (no PK/FK/indexes).
  2. Set-based INSERT...SELECT to add new rows to the target table.
  3. Set-based DELETE to remove stale rows scoped to the import slice.
  4. Drop staging tables.
"""

from typing import List, Tuple, Optional


def bulk_load_presence(
    cursor,
    conn,
    target_table: str,
    id_col_name: str,
    pairs: List[Tuple[int, int]],
    scope_mh_ids: List[int],
    scope_entity_ids: List[int],
    staging_chunk_size: int = 500_000,
    verbose: bool = True,
) -> dict:
    """Load presence pairs via staging tables.

    Args:
        cursor: Active DB cursor.
        conn: Active DB connection.
        target_table: e.g. 'allele_sample_presence' or 'allele_project_presence'.
        id_col_name: 'sample_id' or 'project_id'.
        pairs: (microhaplotype_id, entity_id) tuples where presence=1.
        scope_mh_ids: All microhaplotype IDs covered by this import file.
        scope_entity_ids: All sample/project IDs covered by this import file.
        staging_chunk_size: Rows per staging-load commit.
        verbose: Print progress.

    Returns:
        dict with 'inserted' and 'deleted' counts.
    """
    staging_pairs = f"#stg_{target_table}_pairs"
    staging_mh = f"#stg_{target_table}_mh"
    staging_ent = f"#stg_{target_table}_ent"

    cursor.execute(f"""
        CREATE TABLE {staging_pairs} (
            microhaplotype_id INT NOT NULL,
            {id_col_name} INT NOT NULL
        )
    """)
    cursor.execute(f"""
        CREATE TABLE {staging_mh} (id INT NOT NULL)
    """)
    cursor.execute(f"""
        CREATE TABLE {staging_ent} (id INT NOT NULL)
    """)
    conn.commit()

    if hasattr(cursor, "fast_executemany"):
        cursor.fast_executemany = True

    # -- Load presence pairs into staging in chunks --
    pair_sql = f"INSERT INTO {staging_pairs} (microhaplotype_id, {id_col_name}) VALUES (?, ?)"
    total_pairs = len(pairs)
    for i in range(0, total_pairs, staging_chunk_size):
        chunk = pairs[i : i + staging_chunk_size]
        cursor.executemany(pair_sql, chunk)
        conn.commit()
        if verbose:
            loaded = min(i + staging_chunk_size, total_pairs)
            print(f"  Staging pairs: {loaded:,}/{total_pairs:,}", flush=True)

    # -- Load scope IDs --
    mh_sql = f"INSERT INTO {staging_mh} (id) VALUES (?)"
    for i in range(0, len(scope_mh_ids), staging_chunk_size):
        chunk = [(mid,) for mid in scope_mh_ids[i : i + staging_chunk_size]]
        cursor.executemany(mh_sql, chunk)
        conn.commit()

    ent_sql = f"INSERT INTO {staging_ent} (id) VALUES (?)"
    for i in range(0, len(scope_entity_ids), staging_chunk_size):
        chunk = [(eid,) for eid in scope_entity_ids[i : i + staging_chunk_size]]
        cursor.executemany(ent_sql, chunk)
        conn.commit()

    if verbose:
        print(
            f"  Staging complete: {total_pairs:,} pairs, "
            f"{len(scope_mh_ids):,} allele IDs, {len(scope_entity_ids):,} entity IDs",
            flush=True,
        )

    # -- Set-based INSERT: new rows only --
    if verbose:
        print("  Inserting new presence rows...", flush=True)
    cursor.execute(f"""
        INSERT INTO {target_table} (microhaplotype_id, {id_col_name})
        SELECT s.microhaplotype_id, s.{id_col_name}
        FROM {staging_pairs} s
        WHERE NOT EXISTS (
            SELECT 1 FROM {target_table} t
            WHERE t.microhaplotype_id = s.microhaplotype_id
              AND t.{id_col_name} = s.{id_col_name}
        )
    """)
    inserted = cursor.rowcount
    conn.commit()
    if verbose:
        print(f"  Inserted {inserted:,} new rows", flush=True)

    # -- Set-based DELETE: stale rows in the import scope --
    if verbose:
        print("  Removing stale presence rows...", flush=True)
    cursor.execute(f"""
        DELETE t
        FROM {target_table} t
        WHERE EXISTS (SELECT 1 FROM {staging_mh} WHERE id = t.microhaplotype_id)
          AND EXISTS (SELECT 1 FROM {staging_ent} WHERE id = t.{id_col_name})
          AND NOT EXISTS (
              SELECT 1 FROM {staging_pairs} s
              WHERE s.microhaplotype_id = t.microhaplotype_id
                AND s.{id_col_name} = t.{id_col_name}
          )
    """)
    deleted = cursor.rowcount
    conn.commit()
    if verbose:
        print(f"  Deleted {deleted:,} stale rows", flush=True)

    # -- Cleanup --
    cursor.execute(f"DROP TABLE {staging_pairs}")
    cursor.execute(f"DROP TABLE {staging_mh}")
    cursor.execute(f"DROP TABLE {staging_ent}")
    conn.commit()

    return {"inserted": inserted, "deleted": deleted}


# -- Index / constraint management for Microsoft SQL Server bulk loads --

_PRESENCE_TABLE_META = {
    "allele_sample_presence": {
        "id_col": "sample_id",
        "indexes": [
            ("idx_allele_presence_sample", "sample_id"),
        ],
        "fk_constraints": [
            "FK_allele_sample_presence_microhaplotypes",
            "FK_allele_sample_presence_samples",
        ],
    },
    "allele_project_presence": {
        "id_col": "project_id",
        "indexes": [
            ("idx_allele_project_presence_project", "project_id"),
        ],
        "fk_constraints": [
            "FK_allele_project_presence_microhaplotypes",
            "FK_allele_project_presence_projects",
        ],
    },
}


def disable_constraints_and_indexes(cursor, conn, target_table: str, verbose: bool = True):
    """Drop non-clustered indexes and disable FK checks before bulk load."""
    meta = _PRESENCE_TABLE_META.get(target_table)
    if not meta:
        return

    cursor.execute(f"ALTER TABLE {target_table} NOCHECK CONSTRAINT ALL")

    for idx_name, _ in meta["indexes"]:
        cursor.execute(f"""
            IF EXISTS (
                SELECT 1 FROM sys.indexes
                WHERE name = '{idx_name}'
                  AND object_id = OBJECT_ID('{target_table}')
            )
            DROP INDEX {idx_name} ON {target_table}
        """)
    conn.commit()
    if verbose:
        print(f"  Disabled constraints and dropped indexes on {target_table}", flush=True)


def restore_constraints_and_indexes(cursor, conn, target_table: str, verbose: bool = True):
    """Recreate indexes and re-enable FK checks after bulk load."""
    meta = _PRESENCE_TABLE_META.get(target_table)
    if not meta:
        return

    for idx_name, idx_col in meta["indexes"]:
        cursor.execute(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes
                WHERE name = '{idx_name}'
                  AND object_id = OBJECT_ID('{target_table}')
            )
            CREATE INDEX {idx_name} ON {target_table}({idx_col})
        """)

    cursor.execute(f"ALTER TABLE {target_table} WITH CHECK CHECK CONSTRAINT ALL")
    conn.commit()
    if verbose:
        print(f"  Restored indexes and constraints on {target_table}", flush=True)
