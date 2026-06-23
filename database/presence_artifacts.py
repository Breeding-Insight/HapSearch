"""Compressed filesystem artifacts for large presence/absence matrices."""

import hashlib
import json
import os
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

import config


ARTIFACT_SCHEMA_VERSION = 1
DEFAULT_COMPRESSION = "npz_packbits"


def get_presence_artifact_dir() -> str:
    """Return the configured presence artifact directory."""
    return getattr(
        config,
        "PRESENCE_ARTIFACT_DIR",
        os.path.join(config.DATA_DIR, "presence_artifacts"),
    )


def ensure_artifact_dir(path: Optional[str] = None) -> str:
    """Create and return an artifact directory."""
    output_dir = path or get_presence_artifact_dir()
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _safe_stem(value: str) -> str:
    safe = []
    for ch in str(value):
        if ch.isalnum() or ch in {"-", "_", "."}:
            safe.append(ch)
        else:
            safe.append("_")
    return "".join(safe).strip("_") or "presence"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pack_presence_matrix(
    pairs: Sequence[Tuple[int, int]],
    microhaplotype_ids: Sequence[int],
    entity_ids: Sequence[int],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Pack presence pairs into one bit row per microhaplotype."""
    mh_array = np.array(list(microhaplotype_ids), dtype=np.int64)
    entity_array = np.array(list(entity_ids), dtype=np.int64)
    matrix = np.zeros((len(mh_array), len(entity_array)), dtype=np.bool_)

    mh_pos = {int(mid): i for i, mid in enumerate(mh_array.tolist())}
    entity_pos = {int(eid): i for i, eid in enumerate(entity_array.tolist())}
    for raw_mh_id, raw_entity_id in pairs:
        row = mh_pos.get(int(raw_mh_id))
        col = entity_pos.get(int(raw_entity_id))
        if row is not None and col is not None:
            matrix[row, col] = True

    packed = np.packbits(matrix, axis=1, bitorder="little")
    present_counts = matrix.sum(axis=1).astype(np.int64)
    return mh_array, entity_array, packed, present_counts


def write_presence_bitmap_artifact(
    pairs: Sequence[Tuple[int, int]],
    microhaplotype_ids: Sequence[int],
    entity_ids: Sequence[int],
    *,
    entity_type: str,
    source_path: str,
    species_id: Optional[int] = None,
    project_id: Optional[int] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, object]:
    """Write a compressed bitmap artifact and return metadata for SQL storage."""
    if entity_type not in {"sample", "project"}:
        raise ValueError("entity_type must be 'sample' or 'project'")

    artifact_dir = ensure_artifact_dir(output_dir)
    created_at = int(time.time())
    source_stem = _safe_stem(os.path.splitext(os.path.basename(source_path))[0])
    identity = f"{entity_type}:{species_id}:{project_id}:{source_path}:{created_at}"
    short_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    artifact_name = f"{source_stem}.{entity_type}.{short_hash}.npz"
    artifact_path = os.path.join(artifact_dir, artifact_name)

    mh_array, entity_array, packed, present_counts = _pack_presence_matrix(
        pairs,
        microhaplotype_ids,
        entity_ids,
    )

    np.savez_compressed(
        artifact_path,
        schema_version=np.array([ARTIFACT_SCHEMA_VERSION], dtype=np.int16),
        entity_type=np.array([entity_type]),
        microhaplotype_ids=mh_array,
        entity_ids=entity_array,
        packed_presence=packed,
        present_counts=present_counts,
        entity_count=np.array([len(entity_array)], dtype=np.int64),
        bitorder=np.array(["little"]),
    )

    metadata = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_path": artifact_path,
        "artifact_name": artifact_name,
        "entity_type": entity_type,
        "species_id": species_id,
        "project_id": project_id,
        "source_path": source_path,
        "source_sha256": _sha256_file(source_path) if os.path.exists(source_path) else "",
        "microhaplotype_count": int(len(mh_array)),
        "entity_count": int(len(entity_array)),
        "presence_count": int(sum(present_counts.tolist())),
        "compression": DEFAULT_COMPRESSION,
    }

    json_path = artifact_path + ".json"
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
    metadata["metadata_path"] = json_path
    metadata["artifact_size_bytes"] = os.path.getsize(artifact_path)
    return metadata


def write_presence_lookup_artifact(
    pairs: Sequence[Tuple[int, int]],
    microhaplotype_ids: Sequence[int],
    entity_ids: Sequence[int],
    *,
    entity_type: str,
    source_path: str,
    species_id: Optional[int] = None,
    project_id: Optional[int] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, object]:
    """Write an entity-oriented lookup artifact.

    For sample presence this stores sample rows and microhaplotype columns, which
    supports the UI's "filter haplotypes by sample" path without a relational
    row per presence edge.
    """
    if entity_type not in {"sample_lookup", "project_lookup"}:
        raise ValueError("entity_type must be 'sample_lookup' or 'project_lookup'")

    artifact_dir = ensure_artifact_dir(output_dir)
    created_at = int(time.time())
    source_stem = _safe_stem(os.path.splitext(os.path.basename(source_path))[0])
    identity = f"{entity_type}:{species_id}:{project_id}:{source_path}:{created_at}"
    short_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    artifact_name = f"{source_stem}.{entity_type}.{short_hash}.npz"
    artifact_path = os.path.join(artifact_dir, artifact_name)

    entity_array = np.array(list(entity_ids), dtype=np.int64)
    mh_array = np.array(list(microhaplotype_ids), dtype=np.int64)
    matrix = np.zeros((len(entity_array), len(mh_array)), dtype=np.bool_)
    entity_pos = {int(eid): i for i, eid in enumerate(entity_array.tolist())}
    mh_pos = {int(mid): i for i, mid in enumerate(mh_array.tolist())}

    for raw_mh_id, raw_entity_id in pairs:
        row = entity_pos.get(int(raw_entity_id))
        col = mh_pos.get(int(raw_mh_id))
        if row is not None and col is not None:
            matrix[row, col] = True

    packed = np.packbits(matrix, axis=1, bitorder="little")
    present_counts = matrix.sum(axis=1).astype(np.int64)

    np.savez_compressed(
        artifact_path,
        schema_version=np.array([ARTIFACT_SCHEMA_VERSION], dtype=np.int16),
        entity_type=np.array([entity_type]),
        entity_ids=entity_array,
        microhaplotype_ids=mh_array,
        packed_presence=packed,
        present_counts=present_counts,
        microhaplotype_count=np.array([len(mh_array)], dtype=np.int64),
        bitorder=np.array(["little"]),
    )

    metadata = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_path": artifact_path,
        "artifact_name": artifact_name,
        "entity_type": entity_type,
        "species_id": species_id,
        "project_id": project_id,
        "source_path": source_path,
        "source_sha256": _sha256_file(source_path) if os.path.exists(source_path) else "",
        "microhaplotype_count": int(len(mh_array)),
        "entity_count": int(len(entity_array)),
        "presence_count": int(sum(present_counts.tolist())),
        "compression": DEFAULT_COMPRESSION,
    }
    json_path = artifact_path + ".json"
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
    metadata["metadata_path"] = json_path
    metadata["artifact_size_bytes"] = os.path.getsize(artifact_path)
    return metadata


def read_entity_ids_for_microhaplotype(artifact_path: str, microhaplotype_id: int) -> List[int]:
    """Return present entity IDs for one microhaplotype from a bitmap artifact."""
    with np.load(artifact_path, allow_pickle=False) as data:
        mh_ids = data["microhaplotype_ids"]
        matches = np.where(mh_ids == int(microhaplotype_id))[0]
        if matches.size == 0:
            return []
        row_idx = int(matches[0])
        entity_ids = data["entity_ids"]
        entity_count = int(data["entity_count"][0])
        packed = data["packed_presence"][row_idx]
        bits = np.unpackbits(packed, bitorder="little")[:entity_count]
        present_positions = np.flatnonzero(bits)
        return [int(entity_ids[pos]) for pos in present_positions.tolist()]


def read_microhaplotype_ids_for_entity(artifact_path: str, entity_id: int) -> List[int]:
    """Return present microhaplotype IDs for one sample/project lookup artifact."""
    with np.load(artifact_path, allow_pickle=False) as data:
        entity_ids = data["entity_ids"]
        matches = np.where(entity_ids == int(entity_id))[0]
        if matches.size == 0:
            return []
        row_idx = int(matches[0])
        microhaplotype_ids = data["microhaplotype_ids"]
        microhaplotype_count = int(data["microhaplotype_count"][0])
        packed = data["packed_presence"][row_idx]
        bits = np.unpackbits(packed, bitorder="little")[:microhaplotype_count]
        present_positions = np.flatnonzero(bits)
        return [int(microhaplotype_ids[pos]) for pos in present_positions.tolist()]


def ensure_presence_artifact_schema(cursor) -> None:
    """Create lightweight SQL metadata/summary tables for artifact-backed presence."""
    cursor.execute(
        """
        IF OBJECT_ID('dbo.presence_artifacts', 'U') IS NULL
        BEGIN
            CREATE TABLE presence_artifacts (
                id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
                entity_type NVARCHAR(20) NOT NULL,
                species_id INT NULL,
                project_id INT NULL,
                source_path NVARCHAR(1024) NOT NULL,
                source_sha256 NVARCHAR(64),
                artifact_path NVARCHAR(1024) NOT NULL,
                metadata_path NVARCHAR(1024),
                compression NVARCHAR(50) NOT NULL,
                schema_version INT NOT NULL,
                microhaplotype_count INT NOT NULL,
                entity_count INT NOT NULL,
                presence_count BIGINT NOT NULL,
                artifact_size_bytes BIGINT NULL,
                created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
            )
        END
        """
    )
    cursor.execute(
        """
        IF OBJECT_ID('dbo.microhaplotype_presence_summary', 'U') IS NULL
        BEGIN
            CREATE TABLE microhaplotype_presence_summary (
                microhaplotype_id INT NOT NULL,
                species_id INT NOT NULL,
                entity_type NVARCHAR(20) NOT NULL,
                present_count INT NOT NULL,
                total_count INT NOT NULL,
                frequency FLOAT NOT NULL,
                artifact_id INT NULL,
                updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
                PRIMARY KEY (microhaplotype_id, species_id, entity_type),
                CONSTRAINT FK_presence_summary_microhaplotypes
                    FOREIGN KEY (microhaplotype_id) REFERENCES microhaplotypes(id)
            )
        END
        """
    )


def record_presence_artifact(cursor, metadata: Dict[str, object]) -> Optional[int]:
    """Insert artifact metadata and return the new artifact ID."""
    cursor.execute(
        """
        INSERT INTO presence_artifacts
        (entity_type, species_id, project_id, source_path, source_sha256,
         artifact_path, metadata_path, compression, schema_version,
         microhaplotype_count, entity_count, presence_count, artifact_size_bytes)
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            metadata.get("entity_type"),
            metadata.get("species_id"),
            metadata.get("project_id"),
            metadata.get("source_path"),
            metadata.get("source_sha256"),
            metadata.get("artifact_path"),
            metadata.get("metadata_path"),
            metadata.get("compression"),
            metadata.get("schema_version"),
            metadata.get("microhaplotype_count"),
            metadata.get("entity_count"),
            metadata.get("presence_count"),
            metadata.get("artifact_size_bytes"),
        ),
    )
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else None


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
    if entity_type == "sample":
        merge_sql = """
        MERGE microhaplotype_presence_summary AS target
        USING (
            SELECT
                ? AS microhaplotype_id,
                ? AS species_id,
                ? AS entity_type,
                ? AS present_count,
                ? AS total_count,
                ? AS frequency,
                ? AS artifact_id
        ) AS source
        ON target.microhaplotype_id = source.microhaplotype_id
           AND target.species_id = source.species_id
           AND target.entity_type = source.entity_type
        WHEN MATCHED THEN
            UPDATE SET
                present_count = target.present_count + source.present_count,
                total_count = source.total_count,
                frequency = source.frequency,
                artifact_id = source.artifact_id,
                updated_at = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN
            INSERT (microhaplotype_id, species_id, entity_type, present_count,
                    total_count, frequency, artifact_id)
            VALUES (source.microhaplotype_id, source.species_id, source.entity_type,
                    source.present_count, source.total_count, source.frequency,
                    source.artifact_id);
        """
    else:
        merge_sql = """
        MERGE microhaplotype_presence_summary AS target
        USING (
            SELECT
                ? AS microhaplotype_id,
                ? AS species_id,
                ? AS entity_type,
                ? AS present_count,
                ? AS total_count,
                ? AS frequency,
                ? AS artifact_id
        ) AS source
        ON target.microhaplotype_id = source.microhaplotype_id
           AND target.species_id = source.species_id
           AND target.entity_type = source.entity_type
        WHEN MATCHED THEN
            UPDATE SET
                present_count = source.present_count,
                total_count = source.total_count,
                frequency = source.frequency,
                artifact_id = source.artifact_id,
                updated_at = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN
            INSERT (microhaplotype_id, species_id, entity_type, present_count,
                    total_count, frequency, artifact_id)
            VALUES (source.microhaplotype_id, source.species_id, source.entity_type,
                    source.present_count, source.total_count, source.frequency,
                    source.artifact_id);
        """

    cursor.executemany(merge_sql, params)

    if entity_type == "sample":
        cursor.execute(
            """
            UPDATE microhaplotype_presence_summary
            SET
                total_count = (
                    SELECT COUNT(*)
                    FROM samples
                    WHERE samples.species_id = microhaplotype_presence_summary.species_id
                ),
                frequency = CASE
                    WHEN (
                        SELECT COUNT(*)
                        FROM samples
                        WHERE samples.species_id = microhaplotype_presence_summary.species_id
                    ) > 0
                    THEN CAST(present_count AS FLOAT) / CAST((
                        SELECT COUNT(*)
                        FROM samples
                        WHERE samples.species_id = microhaplotype_presence_summary.species_id
                    ) AS FLOAT)
                    ELSE 0.0
                END,
                updated_at = SYSUTCDATETIME()
            WHERE species_id = ? AND entity_type = 'sample'
            """,
            (int(species_id),),
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
