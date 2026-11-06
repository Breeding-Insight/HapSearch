"""Packed bitmap storage for large presence/absence matrices.

Each imported matrix is one ``presence_artifacts`` row (holding the shared
microhaplotype axis) plus one ``presence_bitmaps`` row per sample or project
whose bits mark which microhaplotypes are present. Both live in the SQLite
database, so the deployed app ships a single file.

Only the entity-oriented layout is stored. Reads in the other direction
(which entities carry a microhaplotype) extract one bit column from the same
matrix, which is cheap once the matrix is cached in memory.
"""

import hashlib
import os
import threading
from collections import OrderedDict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

import config


ARTIFACT_SCHEMA_VERSION = 2
DEFAULT_COMPRESSION = "sqlite_packbits"
ENTITY_TYPES = ("sample", "project")

_cache: "OrderedDict[Tuple[str, int, int], Dict[str, object]]" = OrderedDict()
_cache_bytes = 0
_cache_lock = threading.Lock()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positions(ids: Sequence[int], axis: np.ndarray) -> np.ndarray:
    """Position of each id on an axis of unique ids, or -1 when it isn't there."""
    ids = np.asarray(ids, dtype=np.int64)
    if not len(axis):
        return np.full(len(ids), -1, dtype=np.int64)
    order = np.argsort(axis, kind="stable")
    sorted_axis = axis[order]
    found = np.searchsorted(sorted_axis, ids).clip(0, len(axis) - 1)
    return np.where(sorted_axis[found] == ids, order[found], -1)


def entity_presence_matrix(
    file_presence: np.ndarray,
    row_microhaplotype_ids: Sequence[int],
    column_entity_ids: Sequence[int],
    microhaplotype_ids: Sequence[int],
    entity_ids: Sequence[int],
) -> np.ndarray:
    """Turn an imported matrix into the artifact's entity x microhaplotype matrix.

    file_presence is the file's boolean matrix (one row per allele line, one
    column per sample or project). Rows and columns are placed on the
    artifact's axes by id; ids not on an axis (e.g. unknown alleles, -1) are
    dropped, and repeated rows or columns are OR-ed together. This is the
    vectorized equivalent of building (microhaplotype, entity) pairs.
    """
    mh_axis = np.asarray(list(microhaplotype_ids), dtype=np.int64)
    entity_axis = np.asarray(list(entity_ids), dtype=np.int64)
    matrix = np.zeros((len(entity_axis), len(mh_axis)), dtype=np.bool_)

    row_pos = _positions(row_microhaplotype_ids, mh_axis)
    col_pos = _positions(column_entity_ids, entity_axis)
    rows = np.flatnonzero(row_pos >= 0)
    cols = np.flatnonzero(col_pos >= 0)
    if not len(rows) or not len(cols):
        return matrix

    block = np.asarray(file_presence, dtype=np.bool_)[np.ix_(rows, cols)].T
    target_rows, target_cols = col_pos[cols], row_pos[rows]
    if len(np.unique(target_rows)) == len(target_rows) and len(np.unique(target_cols)) == len(target_cols):
        matrix[np.ix_(target_rows, target_cols)] = block
    else:
        np.logical_or.at(matrix, (target_rows[:, None], target_cols[None, :]), block)
    return matrix


def _pairs_matrix(
    pairs: Sequence[Tuple[int, int]],
    microhaplotype_ids: Sequence[int],
    entity_ids: Sequence[int],
) -> np.ndarray:
    """Entity x microhaplotype matrix from (microhaplotype, entity) pairs."""
    pairs = np.asarray(list(pairs), dtype=np.int64).reshape(-1, 2)
    mh_axis = np.asarray(list(microhaplotype_ids), dtype=np.int64)
    entity_axis = np.asarray(list(entity_ids), dtype=np.int64)
    matrix = np.zeros((len(entity_axis), len(mh_axis)), dtype=np.bool_)
    rows = _positions(pairs[:, 1], entity_axis)
    cols = _positions(pairs[:, 0], mh_axis)
    keep = (rows >= 0) & (cols >= 0)
    matrix[rows[keep], cols[keep]] = True
    return matrix


def _pack_entity_rows(
    pairs: Optional[Sequence[Tuple[int, int]]],
    microhaplotype_ids: Sequence[int],
    entity_ids: Sequence[int],
    matrix: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Pack presence (pairs, or an entity x microhaplotype matrix) into one bit row per entity."""
    entity_array = np.array(list(entity_ids), dtype=np.int64)
    mh_array = np.array(list(microhaplotype_ids), dtype=np.int64)
    if matrix is None:
        matrix = _pairs_matrix(pairs, mh_array, entity_array)
    elif matrix.shape != (len(entity_array), len(mh_array)):
        raise ValueError("presence matrix must be entities x microhaplotypes")

    packed = np.packbits(matrix, axis=1, bitorder="little")
    present_counts = matrix.sum(axis=1).astype(np.int64)
    return mh_array, entity_array, packed, present_counts


def write_presence_artifact(
    cursor,
    pairs: Optional[Sequence[Tuple[int, int]]],
    microhaplotype_ids: Sequence[int],
    entity_ids: Sequence[int],
    *,
    entity_type: str,
    source_path: str,
    species_id: Optional[int] = None,
    project_id: Optional[int] = None,
    matrix: Optional[np.ndarray] = None,
) -> Dict[str, object]:
    """Store a presence matrix as packed bitmap rows and return its metadata.

    Presence is given either as (microhaplotype, entity) pairs or, much faster
    for large imports, as an entity x microhaplotype boolean matrix (see
    entity_presence_matrix); pass pairs=None with a matrix.
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError("entity_type must be 'sample' or 'project'")

    mh_array, entity_array, packed, present_counts = _pack_entity_rows(
        pairs,
        microhaplotype_ids,
        entity_ids,
        matrix,
    )
    artifact_size_bytes = int(packed.nbytes + mh_array.nbytes)
    metadata = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "entity_type": entity_type,
        "species_id": species_id,
        "project_id": project_id,
        "source_path": source_path,
        "source_sha256": _sha256_file(source_path) if os.path.exists(source_path) else "",
        "microhaplotype_count": int(len(mh_array)),
        "entity_count": int(len(entity_array)),
        "presence_count": int(present_counts.sum()),
        "compression": DEFAULT_COMPRESSION,
        "artifact_size_bytes": artifact_size_bytes,
    }

    cursor.execute(
        """
        INSERT INTO presence_artifacts
        (entity_type, species_id, project_id, source_path, source_sha256,
         compression, schema_version, microhaplotype_count, entity_count,
         presence_count, artifact_size_bytes, microhaplotype_ids)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_type,
            species_id,
            project_id,
            source_path,
            metadata["source_sha256"],
            DEFAULT_COMPRESSION,
            ARTIFACT_SCHEMA_VERSION,
            metadata["microhaplotype_count"],
            metadata["entity_count"],
            metadata["presence_count"],
            artifact_size_bytes,
            mh_array.astype("<i8").tobytes(),
        ),
    )
    artifact_id = int(cursor.lastrowid)
    cursor.executemany(
        """
        INSERT INTO presence_bitmaps
        (artifact_id, row_index, entity_id, present_count, packed_presence)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                artifact_id,
                row_index,
                int(entity_array[row_index]),
                int(present_counts[row_index]),
                packed[row_index].tobytes(),
            )
            for row_index in range(len(entity_array))
        ],
    )
    metadata["id"] = artifact_id
    return metadata


def _cache_key(db, artifact_id: int) -> Tuple[str, int, int]:
    # The file's mtime guards local dev, where a rebuilt database reuses IDs.
    db_path = getattr(db, "db_path", None)
    try:
        version = os.stat(db_path).st_mtime_ns if db_path else 0
    except OSError:
        version = 0
    return (str(db_path or id(db)), version, int(artifact_id))


def clear_presence_cache() -> None:
    """Drop all cached matrices (used by tests and after re-imports)."""
    global _cache_bytes
    with _cache_lock:
        _cache.clear()
        _cache_bytes = 0


def _sorted_lookup(ids: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Sorted ids and their original positions, or (None, None) if already sorted.

    Binary search over these arrays costs 12 bytes per id, where a dict of
    id -> position costs around ten times that.
    """
    if len(ids) < 2 or bool(np.all(ids[1:] > ids[:-1])):
        return None, None
    order = np.argsort(ids, kind="stable")
    return ids[order], order.astype(np.int32)


def _find(ids: np.ndarray, sorted_ids: Optional[np.ndarray], order: Optional[np.ndarray], value: int) -> Optional[int]:
    axis = ids if sorted_ids is None else sorted_ids
    pos = int(np.searchsorted(axis, value))
    if pos >= len(axis) or int(axis[pos]) != value:
        return None
    return pos if order is None else int(order[pos])


def entity_row(artifact: Dict[str, object], entity_id: int) -> Optional[int]:
    """Bitmap row of a sample/project in an artifact, or None when it isn't there."""
    return _find(
        artifact["entity_ids"],
        artifact["entity_sorted_ids"],
        artifact["entity_order"],
        int(entity_id),
    )


def microhaplotype_column(artifact: Dict[str, object], microhaplotype_id: int) -> Optional[int]:
    """Bit column of a microhaplotype in an artifact, or None when it isn't there."""
    return _find(
        artifact["microhaplotype_ids"],
        artifact["microhaplotype_sorted_ids"],
        artifact["microhaplotype_order"],
        int(microhaplotype_id),
    )


def _artifact_nbytes(artifact: Dict[str, object]) -> int:
    return sum(value.nbytes for value in artifact.values() if isinstance(value, np.ndarray))


def load_presence_artifact(db, artifact_id: int) -> Dict[str, object]:
    """Return a decoded presence matrix, cached per worker process.

    Artifact rows are immutable once written (re-imports create new IDs), so
    a cached matrix never goes stale. The cache holds at most
    PRESENCE_CACHE_MAX_MB of arrays, dropping the least recently used matrices
    first, so memory stays flat however many species are loaded.
    """
    global _cache_bytes
    key = _cache_key(db, artifact_id)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached

    header_rows = db.execute_query(
        """
        SELECT microhaplotype_ids, microhaplotype_count
        FROM presence_artifacts
        WHERE id = ?
        """,
        (int(artifact_id),),
    )
    if not header_rows:
        raise KeyError(f"Presence artifact {artifact_id} not found")
    header = header_rows[0]
    microhaplotype_count = int(header["microhaplotype_count"])
    microhaplotype_ids = np.frombuffer(header["microhaplotype_ids"], dtype="<i8").astype(np.int64)

    bitmap_rows = db.execute_query(
        """
        SELECT entity_id, packed_presence
        FROM presence_bitmaps
        WHERE artifact_id = ?
        ORDER BY row_index
        """,
        (int(artifact_id),),
    )
    row_bytes = (microhaplotype_count + 7) // 8
    entity_ids = np.array([int(row["entity_id"]) for row in bitmap_rows], dtype=np.int64)
    if bitmap_rows:
        packed_presence = np.frombuffer(
            b"".join(bytes(row["packed_presence"]) for row in bitmap_rows),
            dtype=np.uint8,
        ).reshape(len(bitmap_rows), row_bytes)
    else:
        packed_presence = np.zeros((0, row_bytes), dtype=np.uint8)

    entity_sorted_ids, entity_order = _sorted_lookup(entity_ids)
    microhaplotype_sorted_ids, microhaplotype_order = _sorted_lookup(microhaplotype_ids)
    artifact = {
        "id": int(artifact_id),
        "entity_ids": entity_ids,
        "entity_sorted_ids": entity_sorted_ids,
        "entity_order": entity_order,
        "microhaplotype_ids": microhaplotype_ids,
        "microhaplotype_sorted_ids": microhaplotype_sorted_ids,
        "microhaplotype_order": microhaplotype_order,
        "packed_presence": packed_presence,
        "microhaplotype_count": microhaplotype_count,
    }

    max_bytes = config.PRESENCE_CACHE_MAX_MB * 1024 * 1024
    with _cache_lock:
        if key not in _cache:
            _cache[key] = artifact
            _cache_bytes += _artifact_nbytes(artifact)
        _cache.move_to_end(key)
        # Always keep the newest matrix, even if it alone exceeds the budget.
        while _cache_bytes > max_bytes and len(_cache) > 1:
            _, evicted = _cache.popitem(last=False)
            _cache_bytes -= _artifact_nbytes(evicted)
        artifact = _cache[key]
    return artifact


def microhaplotype_ids_for_entity(
    artifact: Dict[str, object],
    entity_id: int,
) -> List[int]:
    """Return microhaplotype IDs present for one sample/project."""
    row_idx = entity_row(artifact, entity_id)
    if row_idx is None:
        return []

    microhaplotype_ids = artifact["microhaplotype_ids"]
    microhaplotype_count = int(artifact["microhaplotype_count"])
    packed = artifact["packed_presence"][row_idx]
    bits = np.unpackbits(packed, bitorder="little")[:microhaplotype_count]
    present_positions = np.flatnonzero(bits)
    return microhaplotype_ids[present_positions].tolist()


def entity_ids_for_microhaplotype(
    artifact: Dict[str, object],
    microhaplotype_id: int,
) -> List[int]:
    """Return sample/project IDs that carry one microhaplotype."""
    col_idx = microhaplotype_column(artifact, microhaplotype_id)
    if col_idx is None:
        return []

    column = artifact["packed_presence"][:, col_idx >> 3]
    present = (column >> (col_idx & 7)) & 1
    return artifact["entity_ids"][np.flatnonzero(present)].tolist()


def ensure_presence_artifact_schema(cursor) -> None:
    """Create the bitmap and summary tables when importing into an older DB."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS presence_artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK (entity_type IN ('sample', 'project')),
            species_id INTEGER,
            project_id INTEGER,
            source_path TEXT NOT NULL,
            source_sha256 TEXT,
            compression TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            microhaplotype_count INTEGER NOT NULL,
            entity_count INTEGER NOT NULL,
            presence_count INTEGER NOT NULL,
            artifact_size_bytes INTEGER,
            microhaplotype_ids BLOB NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS presence_bitmaps (
            artifact_id INTEGER NOT NULL REFERENCES presence_artifacts(id) ON DELETE CASCADE,
            row_index INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            present_count INTEGER NOT NULL,
            packed_presence BLOB NOT NULL,
            PRIMARY KEY (artifact_id, row_index)
        ) WITHOUT ROWID
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS microhaplotype_presence_summary (
            microhaplotype_id INTEGER NOT NULL REFERENCES microhaplotypes(id),
            species_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            present_count INTEGER NOT NULL,
            total_count INTEGER NOT NULL,
            frequency REAL NOT NULL,
            artifact_id INTEGER REFERENCES presence_artifacts(id),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (microhaplotype_id, species_id, entity_type)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_presence_artifacts_entity "
        "ON presence_artifacts(entity_type, species_id, project_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_presence_bitmaps_entity "
        "ON presence_bitmaps(entity_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_presence_summary_species_entity "
        "ON microhaplotype_presence_summary(species_id, entity_type)"
    )


def upsert_presence_summary(
    cursor,
    *,
    artifact_id: int,
    species_id: int,
    entity_type: str,
    total_count: int,
    counts_by_microhaplotype: Dict[int, int],
) -> None:
    """Maintain compact SQL summary rows for artifact-backed UI queries."""
    if not counts_by_microhaplotype:
        return
    params = [
        (
            int(mid),
            int(species_id),
            entity_type,
            int(present_count),
            int(total_count),
            float(present_count) / float(total_count) if total_count else 0.0,
            int(artifact_id),
        )
        for mid, present_count in counts_by_microhaplotype.items()
    ]
    # Sample imports arrive one project file at a time, so their counts add
    # up; a project matrix covers every project and replaces the old counts.
    present_count_update = (
        "microhaplotype_presence_summary.present_count + excluded.present_count"
        if entity_type == "sample"
        else "excluded.present_count"
    )
    cursor.executemany(
        f"""
        INSERT INTO microhaplotype_presence_summary
        (microhaplotype_id, species_id, entity_type, present_count,
         total_count, frequency, artifact_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (microhaplotype_id, species_id, entity_type) DO UPDATE SET
            present_count = {present_count_update},
            total_count = excluded.total_count,
            frequency = excluded.frequency,
            artifact_id = excluded.artifact_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        params,
    )

    if entity_type == "sample":
        # The species' sample count is the same for every row, so count once
        # rather than in a subquery per row (which grew with every import).
        cursor.execute("SELECT COUNT(*) FROM samples WHERE species_id = ?", (int(species_id),))
        species_samples = int(cursor.fetchone()[0])
        cursor.execute(
            """
            UPDATE microhaplotype_presence_summary
            SET
                total_count = ?,
                frequency = CASE WHEN ? > 0 THEN CAST(present_count AS REAL) / ? ELSE 0.0 END,
                updated_at = CURRENT_TIMESTAMP
            WHERE species_id = ? AND entity_type = 'sample'
            """,
            (species_samples, species_samples, species_samples, int(species_id)),
        )
        cursor.executemany(
            """
            UPDATE microhaplotypes
            SET
                sample_count = (
                    SELECT present_count
                    FROM microhaplotype_presence_summary
                    WHERE microhaplotype_id = microhaplotypes.id
                      AND species_id = ?
                      AND entity_type = 'sample'
                ),
                frequency = (
                    SELECT frequency
                    FROM microhaplotype_presence_summary
                    WHERE microhaplotype_id = microhaplotypes.id
                      AND species_id = ?
                      AND entity_type = 'sample'
                )
            WHERE id = ?
            """,
            [
                (
                    int(species_id),
                    int(species_id),
                    int(mid),
                )
                for mid in counts_by_microhaplotype.keys()
            ],
        )


def counts_from_matrix(matrix: np.ndarray, microhaplotype_ids: Sequence[int]) -> Dict[int, int]:
    """Present entities per microhaplotype from an entity x microhaplotype matrix."""
    counts = np.asarray(matrix, dtype=np.bool_).sum(axis=0)
    return {int(mid): int(count) for mid, count in zip(microhaplotype_ids, counts)}


def counts_by_microhaplotype(
    pairs: Iterable[Tuple[int, int]],
    microhaplotype_ids: Sequence[int],
) -> Dict[int, int]:
    """Count unique present entities for each microhaplotype."""
    observed: Dict[int, set] = {int(mid): set() for mid in microhaplotype_ids}
    for raw_mid, raw_entity in pairs:
        mid = int(raw_mid)
        if mid in observed:
            observed[mid].add(int(raw_entity))
    return {mid: len(entities) for mid, entities in observed.items()}
