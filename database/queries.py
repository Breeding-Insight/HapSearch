"""SQL queries for HaploSearch features"""

from collections import Counter, defaultdict
import random
import re
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from database.db_manager import DatabaseManager
from database.presence_artifacts import (
    read_entity_ids_for_microhaplotype,
    read_microhaplotype_ids_for_entity,
    load_lookup_artifact,
    read_microhaplotype_ids_from_loaded_lookup,
)

_PROJECT_PREFIX_RE = re.compile(r'^(P\d+)')
_JUNK_PROJECT_NAMES = frozenset({'count', '12plates', '2plates'})
_SAFE_SQL_PARAM_LIMIT = 1800
_BYTE_POPCOUNT = np.array([int(value).bit_count() for value in range(256)], dtype=np.uint16)


def _normalize_pi_name(raw: str) -> str:
    """Sort semicolon/comma-separated owner names for stable comparison."""
    parts = sorted(
        n.strip() for n in re.split(r'[;,]', raw) if n.strip()
    )
    return ';'.join(parts)


def _project_dedup_key(project: Dict[str, Any]) -> tuple:
    """Stable dedup key: (P## prefix, project_name, normalized pi_name).

    Multiple import runs created duplicate project records with slightly
    different ``project_code`` formats (hyphens vs underscores, with/without
    plate counts).  The P## prefix, ``project_name``, and ``pi_name`` are
    stable across all generations.  Including ``pi_name`` ensures that
    distinct sub-projects sharing the same prefix and informal name (e.g.
    P14 Salinity - Ali vs Devinder) are not collapsed.
    """
    code = str(project.get('project_code') or '')
    name = (project.get('project_name') or '').strip()
    pi = _normalize_pi_name(project.get('pi_name') or '')
    m = _PROJECT_PREFIX_RE.match(code)
    prefix = m.group(1) if m else code
    return (prefix, name, pi)


def _deduplicate_projects(project_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse duplicate project records, keeping one representative per logical project."""
    seen: dict = {}
    for p in project_rows:
        name = (p.get('project_name') or '').strip()
        if name in _JUNK_PROJECT_NAMES:
            continue
        key = _project_dedup_key(p)
        if key in seen:
            existing = seen[key]
            existing.setdefault('_all_ids', set()).add(p.get('id'))
            for k, v in p.items():
                if v is not None and k != '_all_ids':
                    existing[k] = v
        else:
            p_copy = dict(p)
            p_copy['_all_ids'] = {p.get('id')}
            seen[key] = p_copy
    return list(seen.values())


def _chunks(items: List[int], size: int = 400):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _get_microhaplotype_ids_for_sample_filter_artifacts(
    db: DatabaseManager,
    sample_filter: str,
    species_id: int = None,
) -> List[int]:
    """Resolve sample-name filtering through sample-oriented bitmap artifacts."""
    if not sample_filter:
        return []

    sample_query = "SELECT id FROM samples WHERE sample_code LIKE ?"
    sample_params: List[Any] = [f"%{sample_filter}%"]
    if species_id:
        sample_query += " AND species_id = ?"
        sample_params.append(species_id)
    sample_rows = db.execute_query(sample_query, tuple(sample_params))
    sample_ids = [int(row["id"]) for row in sample_rows if row.get("id") is not None]
    if not sample_ids:
        return []

    artifact_query = """
        SELECT artifact_path
        FROM presence_artifacts
        WHERE entity_type = 'sample_lookup'
    """
    artifact_params: List[Any] = []
    if species_id:
        artifact_query += " AND species_id = ?"
        artifact_params.append(species_id)
    artifact_rows = db.execute_query(artifact_query, tuple(artifact_params))
    artifact_paths = [row["artifact_path"] for row in artifact_rows if row.get("artifact_path")]
    if not artifact_paths:
        return []

    microhaplotype_ids = set()
    for artifact_path in artifact_paths:
        for sample_id in sample_ids:
            try:
                microhaplotype_ids.update(
                    read_microhaplotype_ids_for_entity(artifact_path, sample_id)
                )
            except Exception:
                continue

    return sorted(microhaplotype_ids)


def _run_chunked_microhaplotype_id_filter(
    db: DatabaseManager,
    ordered_query: str,
    base_params: List[Any],
    microhaplotype_ids: List[int],
    page: int,
    per_page: int,
) -> Dict[str, Any]:
    """Apply a large artifact-backed ID filter without truncating matches."""
    query_no_order = ordered_query.rsplit(" ORDER BY ", 1)[0]
    chunk_size = max(1, _SAFE_SQL_PARAM_LIMIT - len(base_params))
    rows: List[Dict[str, Any]] = []

    for chunk in _chunks(microhaplotype_ids, chunk_size):
        placeholders = ",".join(["?"] * len(chunk))
        chunk_query = f"{query_no_order} AND m.id IN ({placeholders})"
        rows.extend(db.execute_query(chunk_query, tuple(base_params + chunk)))

    rows.sort(key=lambda row: str(row.get("haplotype_name") or ""))
    total = len(rows)
    offset = (page - 1) * per_page

    return {
        'microhaplotypes': rows[offset:offset + per_page],
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if per_page > 0 else 0
    }


def _get_entity_ids_for_haplotype_artifacts(
    db: DatabaseManager,
    haplotype_name: str,
    entity_type: str,
) -> List[int]:
    """Return present sample/project IDs for a haplotype across all artifacts."""
    artifact_query = """
        SELECT
            m.id AS microhaplotype_id,
            pa.artifact_path
        FROM microhaplotypes m
        JOIN markers mk ON mk.id = m.marker_id
        JOIN chromosomes c ON c.id = mk.chromosome_id
        JOIN presence_artifacts pa
          ON pa.species_id = c.species_id
         AND pa.entity_type = ?
        WHERE m.haplotype_name = ?
        ORDER BY pa.created_at
    """
    artifact_rows = db.execute_query(artifact_query, (entity_type, haplotype_name))
    entity_ids = set()
    for artifact in artifact_rows:
        try:
            entity_ids.update(
                read_entity_ids_for_microhaplotype(
                    artifact["artifact_path"],
                    int(artifact["microhaplotype_id"]),
                )
            )
        except Exception:
            continue
    return sorted(entity_ids)


def get_all_species(db: DatabaseManager) -> List[Dict[str, Any]]:
    """Get all species with counts"""
    query = """
        SELECT
            s.id,
            s.name,
            s.common_name,
            s.description,
            COUNT(DISTINCT c.id) as chromosome_count,
            COUNT(DISTINCT mk.id) as marker_count,
            COUNT(DISTINCT m.id) as microhaplotype_count
        FROM species s
        LEFT JOIN chromosomes c ON s.id = c.species_id
        LEFT JOIN markers mk ON c.id = mk.chromosome_id
        LEFT JOIN microhaplotypes m ON mk.id = m.marker_id
        GROUP BY s.id, s.name, s.common_name, s.description
        ORDER BY s.name
    """
    return db.execute_query(query)


def get_chromosome_counts(db: DatabaseManager, species_id: int) -> List[Dict[str, Any]]:
    """Get microhaplotype counts per chromosome for a species (Feature 1)"""
    query = """
        SELECT
            c.chromosome_name,
            c.microhaplotype_count,
            COUNT(DISTINCT mk.id) as marker_count
        FROM chromosomes c
        LEFT JOIN markers mk ON c.id = mk.chromosome_id
        WHERE c.species_id = ?
        GROUP BY c.id, c.chromosome_name, c.microhaplotype_count
        ORDER BY c.chromosome_name
    """
    return db.execute_query(query, (species_id,))


def search_markers(db: DatabaseManager, search_term: str = None,
                  species_id: int = None) -> List[Dict[str, Any]]:
    """Search for markers by ID or description"""
    query = """
        SELECT
            mk.id,
            mk.marker_id,
            mk.marker_type,
            mk.description,
            mk.position_start,
            mk.position_end,
            c.chromosome_name,
            s.name as species_name,
            COUNT(DISTINCT m.id) as microhaplotype_count
        FROM markers mk
        JOIN chromosomes c ON mk.chromosome_id = c.id
        JOIN species s ON c.species_id = s.id
        LEFT JOIN microhaplotypes m ON mk.id = m.marker_id
        WHERE 1=1
    """
    params = []

    if search_term:
        query += " AND (mk.marker_id LIKE ? OR mk.description LIKE ?)"
        search_pattern = f"%{search_term}%"
        params.extend([search_pattern, search_pattern])

    if species_id:
        query += " AND s.id = ?"
        params.append(species_id)

    query += (
        " GROUP BY mk.id, mk.marker_id, mk.marker_type, mk.description, "
        "mk.position_start, mk.position_end, c.chromosome_name, s.name "
        "ORDER BY mk.marker_id"
    )

    return db.execute_query(query, tuple(params))


def get_marker_details(db: DatabaseManager, marker_id: str) -> Dict[str, Any]:
    """Get detailed information for a specific marker (Feature 2)"""
    query = """
        SELECT
            mk.id,
            mk.marker_id,
            mk.marker_type,
            mk.description,
            mk.position_start,
            mk.position_end,
            c.chromosome_name,
            s.name as species_name,
            s.id as species_id
        FROM markers mk
        JOIN chromosomes c ON mk.chromosome_id = c.id
        JOIN species s ON c.species_id = s.id
        WHERE mk.marker_id = ?
    """
    results = db.execute_query(query, (marker_id,))
    return results[0] if results else None


def get_microhaplotypes_for_marker(db: DatabaseManager, marker_id: str) -> List[Dict[str, Any]]:
    """Get all microhaplotypes for a marker (Feature 2)"""
    query = """
        SELECT
            m.id,
            m.haplotype_name,
            m.haplotype_sequence,
            m.frequency,
            m.sample_count
        FROM microhaplotypes m
        JOIN markers mk ON m.marker_id = mk.id
        WHERE mk.marker_id = ?
        ORDER BY m.frequency DESC
    """
    return db.execute_query(query, (marker_id,))


def get_variants_for_marker(db: DatabaseManager, marker_id: str) -> List[Dict[str, Any]]:
    """Get all variants for a marker (Feature 2)"""
    query = """
        SELECT
            v.position,
            v.variant_type,
            v.reference_allele,
            v.alternate_allele,
            v.frequency
        FROM variants v
        JOIN markers mk ON v.marker_id = mk.id
        WHERE mk.marker_id = ?
        ORDER BY v.position
    """
    return db.execute_query(query, (marker_id,))


def ensure_botloci_table(db: DatabaseManager) -> None:
    """Create the bottom-loci lookup table if it is missing."""
    db.execute_update("""
        IF OBJECT_ID(N'[dbo].[botloci]', N'U') IS NULL
        BEGIN
            CREATE TABLE botloci (
                id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
                marker_id NVARCHAR(255) NOT NULL UNIQUE,
                created_at DATETIME DEFAULT GETDATE()
            )
        END
    """)
    db.execute_update("""
        IF OBJECT_ID(N'[dbo].[botloci]', N'U') IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
               FROM sys.indexes
               WHERE name = 'idx_botloci_marker_id'
                 AND object_id = OBJECT_ID(N'[dbo].[botloci]')
           )
        BEGIN
            CREATE INDEX idx_botloci_marker_id ON botloci(marker_id)
        END
    """)


def botloci_table_exists(db: DatabaseManager) -> bool:
    """Return whether the bottom-loci lookup table exists."""
    try:
        return db.table_exists('botloci')
    except Exception:
        return False


def get_botloci_count(db: DatabaseManager) -> int:
    """Return stored bottom-loci count, treating a missing table as empty."""
    if not botloci_table_exists(db):
        return 0
    try:
        result = db.execute_query("SELECT COUNT(*) as count FROM botloci")
        return result[0]['count'] if result else 0
    except Exception:
        return 0


def is_bottom_locus(db: DatabaseManager, marker_id: str) -> bool:
    """Return True when the marker is listed in the bottom-loci lookup."""
    if not marker_id or not botloci_table_exists(db):
        return False
    try:
        result = db.execute_query(
            "SELECT TOP 1 marker_id FROM botloci WHERE marker_id = ?",
            (marker_id,),
        )
        return bool(result)
    except Exception:
        return False


def upsert_botloci(db: DatabaseManager, marker_ids: List[str]) -> int:
    """Insert bottom-loci marker IDs, ignoring existing rows."""
    if not marker_ids:
        return 0

    ensure_botloci_table(db)
    inserted = 0
    with db.get_connection() as conn:
        cursor = conn.cursor()
        for marker_id in marker_ids:
            cursor.execute("SELECT 1 FROM botloci WHERE marker_id = ?", (marker_id,))
            if cursor.fetchone():
                continue
            cursor.execute("INSERT INTO botloci (marker_id) VALUES (?)", (marker_id,))
            inserted += 1
    return inserted


def search_microhaplotypes(db: DatabaseManager, search_term: str = None,
                          species_id: int = None) -> List[Dict[str, Any]]:
    """Search for microhaplotypes"""
    query = """
        SELECT
            m.id,
            m.haplotype_name,
            m.haplotype_sequence,
            m.frequency,
            m.sample_count,
            mk.marker_id,
            s.name as species_name
        FROM microhaplotypes m
        JOIN markers mk ON m.marker_id = mk.id
        JOIN chromosomes c ON mk.chromosome_id = c.id
        JOIN species s ON c.species_id = s.id
        WHERE 1=1
    """
    params = []

    if search_term:
        query += " AND (m.haplotype_name LIKE ? OR m.haplotype_sequence LIKE ?)"
        search_pattern = f"%{search_term}%"
        params.extend([search_pattern, search_pattern])

    if species_id:
        query += " AND s.id = ?"
        params.append(species_id)

    query += " ORDER BY m.haplotype_name LIMIT 100"

    return db.execute_query(query, tuple(params))


def get_samples_for_microhaplotype(db: DatabaseManager,
                                   haplotype_name: str) -> List[Dict[str, Any]]:
    """Get samples containing a specific microhaplotype (Feature 3)"""
    query = """
        SELECT
            s.sample_code,
            s.collection_date,
            s.collection_location,
            s.sample_type,
            p.project_code,
            p.project_name,
            p.pi_name,
            ms.read_count,
            sp.name as species_name
        FROM microhaplotype_samples ms
        JOIN microhaplotypes m ON ms.microhaplotype_id = m.id
        JOIN samples s ON ms.sample_id = s.id
        JOIN projects p ON s.project_id = p.id
        JOIN species sp ON s.species_id = sp.id
        WHERE m.haplotype_name = ?
        ORDER BY p.project_code, s.sample_code
    """
    return db.execute_query(query, (haplotype_name,))


def get_projects_for_microhaplotype(db: DatabaseManager,
                                   haplotype_name: str) -> List[Dict[str, Any]]:
    """Get projects associated with a microhaplotype (Features 3 & 4)"""
    query = """
        SELECT
            p.id,
            p.project_code,
            p.project_name,
            p.pi_name,
            p.pi_email,
            p.pi_institution,
            p.pi_department,
            p.description,
            p.start_date,
            COUNT(DISTINCT s.id) as total_samples,
            COUNT(DISTINCT ms.sample_id) as samples_with_haplotype,
            sp.name as species_name
        FROM microhaplotype_samples ms
        JOIN microhaplotypes m ON ms.microhaplotype_id = m.id
        JOIN samples s ON ms.sample_id = s.id
        JOIN projects p ON s.project_id = p.id
        JOIN species sp ON s.species_id = sp.id
        WHERE m.haplotype_name = ?
        GROUP BY
            p.id, p.project_code, p.project_name, p.pi_name, p.pi_email,
            p.pi_institution, p.pi_department, p.description, p.start_date, sp.name
        ORDER BY samples_with_haplotype DESC
    """
    return db.execute_query(query, (haplotype_name,))


def get_database_statistics(db: DatabaseManager) -> Dict[str, int]:
    """Get overall database statistics"""
    stats = {
        'species_count': db.get_table_row_count('species'),
        'chromosome_count': db.get_table_row_count('chromosomes'),
        'marker_count': db.get_table_row_count('markers'),
        'microhaplotype_count': db.get_table_row_count('microhaplotypes'),
        'variant_count': db.get_table_row_count('variants'),
        'project_count': db.get_table_row_count('projects'),
        'sample_count': db.get_table_row_count('samples'),
        'association_count': db.get_table_row_count('microhaplotype_samples')
    }
    return stats


def get_species_statistics(db: DatabaseManager, species_id: int) -> Dict[str, Any]:
    """Get statistics for a specific species"""
    query = """
        SELECT
            COUNT(DISTINCT c.id) as chromosome_count,
            COUNT(DISTINCT mk.id) as marker_count,
            COUNT(DISTINCT m.id) as microhaplotype_count,
            COUNT(DISTINCT v.id) as variant_count,
            COUNT(DISTINCT s.id) as sample_count
        FROM species sp
        LEFT JOIN chromosomes c ON sp.id = c.species_id
        LEFT JOIN markers mk ON c.id = mk.chromosome_id
        LEFT JOIN microhaplotypes m ON mk.id = m.marker_id
        LEFT JOIN variants v ON mk.id = v.marker_id
        LEFT JOIN samples s ON sp.id = s.species_id
        WHERE sp.id = ?
    """
    results = db.execute_query(query, (species_id,))
    return results[0] if results else {}


def get_autocomplete_markers(db: DatabaseManager, prefix: str,
                            limit: int = 10) -> List[str]:
    """Get marker IDs for autocomplete"""
    query = """
        SELECT DISTINCT marker_id
        FROM markers
        WHERE marker_id LIKE ?
        ORDER BY marker_id
        LIMIT ?
    """
    results = db.execute_query(query, (f"{prefix}%", limit))
    return [r['marker_id'] for r in results]


def get_autocomplete_haplotypes(db: DatabaseManager, prefix: str,
                               limit: int = 10) -> List[str]:
    """Get haplotype names for autocomplete"""
    query = """
        SELECT DISTINCT haplotype_name
        FROM microhaplotypes
        WHERE haplotype_name LIKE ?
        ORDER BY haplotype_name
        LIMIT ?
    """
    results = db.execute_query(query, (f"{prefix}%", limit))
    return [r['haplotype_name'] for r in results]


def get_allele_density_by_position(db: DatabaseManager, species_id: int,
                                   chromosome_name: str = None) -> List[Dict[str, Any]]:
    """Get allele counts across genomic positions for density visualization"""
    query = """
        SELECT
            c.chromosome_name,
            mk.position_start as position,
            COUNT(DISTINCT m.id) as allele_count,
            mk.marker_id
        FROM markers mk
        JOIN chromosomes c ON mk.chromosome_id = c.id
        JOIN species s ON c.species_id = s.id
        LEFT JOIN microhaplotypes m ON mk.id = m.marker_id
        WHERE s.id = ?
    """
    params = [species_id]

    if chromosome_name:
        query += " AND c.chromosome_name = ?"
        params.append(chromosome_name)

    query += """
        GROUP BY c.chromosome_name, mk.position_start, mk.marker_id
        ORDER BY c.chromosome_name, mk.position_start
    """

    return db.execute_query(query, tuple(params))


def get_position_range_for_chromosome(db: DatabaseManager, species_id: int,
                                      chromosome_name: str) -> Dict[str, int]:
    """Get min and max positions for a chromosome"""
    query = """
        SELECT
            MIN(mk.position_start) as min_position,
            MAX(mk.position_start) as max_position,
            COUNT(DISTINCT mk.id) as marker_count
        FROM markers mk
        JOIN chromosomes c ON mk.chromosome_id = c.id
        WHERE c.species_id = ? AND c.chromosome_name = ?
    """
    results = db.execute_query(query, (species_id, chromosome_name))
    return results[0] if results else {'min_position': 0, 'max_position': 0, 'marker_count': 0}


# Additional helper functions for Haplosearch

def get_markers_paginated(db: DatabaseManager, species_id: int = None,
                         chromosome_id: int = None, search_marker_id: str = None,
                         search_sequence: str = None, page: int = 1, per_page: int = 25) -> Dict[str, Any]:
    """Get paginated markers with filtering"""
    query = """
        SELECT
            mk.id,
            mk.marker_id,
            mk.marker_type,
            mk.description,
            mk.position_start,
            mk.position_end,
            c.chromosome_name,
            s.name as species_name,
            COUNT(DISTINCT m.id) as microhaplotype_count
        FROM markers mk
        JOIN chromosomes c ON mk.chromosome_id = c.id
        JOIN species s ON c.species_id = s.id
        LEFT JOIN microhaplotypes m ON mk.id = m.marker_id
        WHERE 1=1
    """
    params = []

    if species_id:
        query += " AND s.id = ?"
        params.append(species_id)

    if chromosome_id:
        query += " AND c.id = ?"
        params.append(chromosome_id)

    if search_marker_id:
        query += " AND mk.marker_id LIKE ?"
        params.append(f"%{search_marker_id}%")

    if search_sequence:
        # Filter markers that have at least one microhaplotype containing the exact search sequence as a substring
        # Use INSTR for case-insensitive exact sequence matching (returns position if found, 0 if not)
        query += " AND EXISTS (SELECT 1 FROM microhaplotypes m2 WHERE m2.marker_id = mk.id AND INSTR(UPPER(m2.haplotype_sequence), UPPER(?)) > 0)"
        params.append(search_sequence)

    query += (
        " GROUP BY mk.id, mk.marker_id, mk.marker_type, mk.description, "
        "mk.position_start, mk.position_end, c.chromosome_name, s.name "
        "ORDER BY mk.marker_id"
    )

    # Get total count
    query_no_order = query.rsplit(" ORDER BY ", 1)[0]
    count_query = f"SELECT COUNT(*) as total FROM ({query_no_order}) as subquery"
    total_result = db.execute_query(count_query, tuple(params))
    total = total_result[0]['total'] if total_result else 0

    # Add pagination
    offset = (page - 1) * per_page
    query += f" LIMIT {per_page} OFFSET {offset}"

    markers = db.execute_query(query, tuple(params))

    return {
        'markers': markers,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if per_page > 0 else 0
    }


def get_microhaplotypes_paginated(
    db: DatabaseManager,
    species_id: int = None,
    chromosome_id: int = None,
    search_name: str = None,
    search_sequence: str = None,
    marker_id: str = None,
    sample_filter: str = None,
    min_frequency: float = None,
    max_frequency: float = None,
    exclude_missing_samples: bool = False,
    page: int = 1,
    per_page: int = 25
) -> Dict[str, Any]:
    """Get paginated microhaplotypes with filtering"""
    # Explorer filtering relies on the stored microhaplotypes.frequency, which is updated
    # (species-based) by database.db_manager.update_haplotype_frequencies().
    query = """
        SELECT
            m.id,
            m.haplotype_name,
            m.haplotype_sequence,
            m.frequency,
            m.sample_count,
            mk.marker_id,
            sp.id as species_id,
            sp.name as species_name,
            (
                SELECT COUNT(*)
                FROM samples s_count
                WHERE s_count.species_id = sp.id
            ) as species_sample_count
        FROM microhaplotypes m
        JOIN markers mk ON m.marker_id = mk.id
        JOIN chromosomes c ON mk.chromosome_id = c.id
        JOIN species sp ON c.species_id = sp.id
        WHERE 1=1
    """
    params = []
    chunked_sample_microhaplotype_ids = None

    if species_id:
        query += " AND sp.id = ?"
        params.append(species_id)

    if chromosome_id:
        query += " AND c.id = ?"
        params.append(chromosome_id)

    if search_name:
        query += " AND m.haplotype_name LIKE ?"
        params.append(f"%{search_name}%")

    if search_sequence:
        query += " AND m.haplotype_sequence LIKE ?"
        params.append(f"%{search_sequence}%")

    if marker_id:
        query += " AND mk.marker_id LIKE ?"
        params.append(f"%{marker_id}%")

    if sample_filter:
        # Filter haplotypes by sample code/name (supports substring match).
        artifact_microhaplotype_ids = _get_microhaplotype_ids_for_sample_filter_artifacts(
            db,
            sample_filter,
            species_id,
        )
        if artifact_microhaplotype_ids:
            remaining_param_capacity = _SAFE_SQL_PARAM_LIMIT - len(params)
            if len(artifact_microhaplotype_ids) <= remaining_param_capacity:
                artifact_placeholders = ",".join(["?"] * len(artifact_microhaplotype_ids))
                query += f" AND m.id IN ({artifact_placeholders})"
                params.extend(artifact_microhaplotype_ids)
            else:
                chunked_sample_microhaplotype_ids = artifact_microhaplotype_ids
        else:
            query += " AND 1 = 0"

    if min_frequency is not None:
        query += " AND m.frequency >= ?"
        params.append(float(min_frequency))

    if max_frequency is not None:
        query += " AND m.frequency <= ?"
        params.append(float(max_frequency))

    excludes_na_frequency = (
        exclude_missing_samples
        or (min_frequency is not None and float(min_frequency) > 0.0)
    )
    if excludes_na_frequency:
        query += " AND EXISTS (SELECT 1 FROM samples s3 WHERE s3.species_id = sp.id)"
        query += " AND COALESCE(m.sample_count, 0) > 0"

    query += " ORDER BY m.haplotype_name"

    if chunked_sample_microhaplotype_ids is not None:
        return _run_chunked_microhaplotype_id_filter(
            db,
            query,
            params,
            chunked_sample_microhaplotype_ids,
            page,
            per_page,
        )

    # Get total count
    query_no_order = query.rsplit(" ORDER BY ", 1)[0]
    count_query = f"SELECT COUNT(*) as total FROM ({query_no_order}) as subquery"
    total_result = db.execute_query(count_query, tuple(params))
    total = total_result[0]['total'] if total_result else 0

    # Add pagination
    offset = (page - 1) * per_page
    query += f" LIMIT {per_page} OFFSET {offset}"

    microhaplotypes = db.execute_query(query, tuple(params))

    return {
        'microhaplotypes': microhaplotypes,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if per_page > 0 else 0
    }


def get_species_sample_count(db: DatabaseManager, species_id: int) -> int:
    """Get total number of samples linked to a species."""
    if not species_id:
        return 0
    query = "SELECT COUNT(*) as total FROM samples WHERE species_id = ?"
    results = db.execute_query(query, (species_id,))
    return int(results[0]['total']) if results else 0


def get_species_snapshot(db: DatabaseManager, species_id: int) -> Dict[str, Any]:
    """Compact species-level stats for the overview snapshot panel.

    Uses separate queries to avoid a cartesian product between the
    marker/microhaplotype chain and the samples table.
    """
    if not species_id:
        return {}

    species_query = """
        SELECT
            name,
            common_name
        FROM species
        WHERE id = ?
    """
    species_rows = db.execute_query(species_query, (species_id,))
    species = species_rows[0] if species_rows else {}
    scientific_name = (species.get('name') or '').strip()
    common_name = (species.get('common_name') or '').strip()
    if common_name and scientific_name:
        species_label = f"{common_name} ({scientific_name})"
    else:
        species_label = common_name or scientific_name or "Selected Species"

    marker_micro_query = """
        SELECT
            COUNT(DISTINCT mk.id) AS marker_count,
            COUNT(DISTINCT m.id) AS microhaplotype_count
        FROM chromosomes c
        JOIN markers mk ON c.id = mk.chromosome_id
        LEFT JOIN microhaplotypes m ON mk.id = m.marker_id
        WHERE c.species_id = ?
    """
    mm_rows = db.execute_query(marker_micro_query, (species_id,))
    mm = mm_rows[0] if mm_rows else {}
    marker_count = (mm.get('marker_count') or 0)
    microhaplotype_count = (mm.get('microhaplotype_count') or 0)

    sample_count_query = """
        SELECT COUNT(*) AS sample_count FROM samples WHERE species_id = ?
    """
    sc_rows = db.execute_query(sample_count_query, (species_id,))
    sample_count = (sc_rows[0].get('sample_count') or 0) if sc_rows else 0

    sample_projects_query = """
        SELECT p.id, p.project_code, p.project_name, p.pi_name
        FROM projects p
        WHERE EXISTS (SELECT 1 FROM samples s WHERE s.project_id = p.id AND s.species_id = ?)
    """
    all_proj_rows = db.execute_query(sample_projects_query, (species_id,))
    deduped = _deduplicate_projects(all_proj_rows)
    project_count = len(deduped)
    artifact_project_query = """
        SELECT MAX(total_count) AS project_count
        FROM microhaplotype_presence_summary
        WHERE species_id = ? AND entity_type = 'project'
    """
    artifact_project_rows = db.execute_query(artifact_project_query, (species_id,))
    if artifact_project_rows:
        project_count = max(project_count, int(artifact_project_rows[0].get('project_count') or 0))

    avg_alleles = round(microhaplotype_count / marker_count, 1) if marker_count else 0.0

    rare_query = """
        SELECT COUNT(*) AS rare_count
        FROM microhaplotypes m
        JOIN markers mk ON m.marker_id = mk.id
        JOIN chromosomes c ON mk.chromosome_id = c.id
        WHERE c.species_id = ?
          AND m.frequency <= 0.01
          AND COALESCE(m.sample_count, 0) > 0
    """
    rare_rows = db.execute_query(rare_query, (species_id,))
    rare_microhaplotypes = (rare_rows[0]['rare_count'] if rare_rows else 0) or 0

    return {
        'species_label': species_label,
        'marker_count': marker_count,
        'microhaplotype_count': microhaplotype_count,
        'avg_alleles_per_marker': avg_alleles,
        'sample_count': sample_count,
        'project_count': project_count,
        'rare_microhaplotypes': rare_microhaplotypes,
    }


def get_all_chromosomes_for_species(db: DatabaseManager, species_id: int) -> List[Dict[str, Any]]:
    """Get all chromosomes for a species"""
    query = """
        SELECT
            id,
            chromosome_name,
            length,
            microhaplotype_count
        FROM chromosomes
        WHERE species_id = ?
        ORDER BY chromosome_name
    """
    return db.execute_query(query, (species_id,))


def get_microhaplotype_details(db: DatabaseManager, haplotype_name: str) -> Dict[str, Any]:
    """Get detailed information for a specific microhaplotype"""
    query = """
        SELECT
            m.id,
            m.haplotype_name,
            m.haplotype_sequence,
            m.frequency,
            m.sample_count,
            mk.marker_id,
            s.name as species_name,
            s.id as species_id
        FROM microhaplotypes m
        JOIN markers mk ON m.marker_id = mk.id
        JOIN chromosomes c ON mk.chromosome_id = c.id
        JOIN species s ON c.species_id = s.id
        WHERE m.haplotype_name = ?
    """
    results = db.execute_query(query, (haplotype_name,))
    return results[0] if results else None


def get_samples_for_allele(db: DatabaseManager, haplotype_name: str) -> List[Dict[str, Any]]:
    """Get all samples with presence for an allele from compressed artifacts."""
    sample_ids = _get_entity_ids_for_haplotype_artifacts(db, haplotype_name, "sample")
    if not sample_ids:
        return []

    results: List[Dict[str, Any]] = []
    for i in range(0, len(sample_ids), 400):
        chunk = sample_ids[i:i + 400]
        placeholders = ",".join(["?"] * len(chunk))
        sample_query = f"""
            SELECT
                s.sample_code,
                1 as presence,
                s.sample_type,
                s.collection_date,
                s.collection_location,
                p.project_code,
                p.project_name,
                p.pi_name,
                sp.name as species_name
            FROM samples s
            JOIN projects p ON s.project_id = p.id
            JOIN species sp ON s.species_id = sp.id
            WHERE s.id IN ({placeholders})
            ORDER BY p.project_code, s.sample_code
        """
        results.extend(db.execute_query(sample_query, tuple(chunk)))
    return sorted(results, key=lambda r: (r.get("project_code") or "", r.get("sample_code") or ""))


def get_alleles_for_sample(db: DatabaseManager, sample_code: str) -> List[Dict[str, Any]]:
    """Get all alleles present in a sample from compressed lookup artifacts."""
    sample_rows = db.execute_query(
        "SELECT id, species_id FROM samples WHERE sample_code = ?",
        (sample_code,),
    )
    if not sample_rows:
        return []

    sample_id = int(sample_rows[0]["id"])
    species_id = int(sample_rows[0]["species_id"])
    artifact_rows = db.execute_query(
        """
        SELECT artifact_path
        FROM presence_artifacts
        WHERE entity_type = 'sample_lookup'
          AND species_id = ?
        ORDER BY created_at DESC
        """,
        (species_id,),
    )
    microhaplotype_ids = set()
    for artifact in artifact_rows:
        try:
            microhaplotype_ids.update(
                read_microhaplotype_ids_for_entity(artifact["artifact_path"], sample_id)
            )
        except Exception:
            continue
    if not microhaplotype_ids:
        return []

    results: List[Dict[str, Any]] = []
    for chunk in _chunks(sorted(microhaplotype_ids)):
        placeholders = ",".join(["?"] * len(chunk))
        query = f"""
            SELECT
                m.haplotype_name,
                1 as presence,
                m.haplotype_sequence,
                m.frequency,
                mk.marker_id,
                sp.name as species_name
            FROM microhaplotypes m
            JOIN markers mk ON m.marker_id = mk.id
            JOIN chromosomes c ON mk.chromosome_id = c.id
            JOIN species sp ON c.species_id = sp.id
            WHERE m.id IN ({placeholders})
            ORDER BY mk.marker_id, m.haplotype_name
        """
        results.extend(db.execute_query(query, tuple(chunk)))
    return sorted(results, key=lambda r: (r.get("marker_id") or "", r.get("haplotype_name") or ""))


def get_presence_statistics(
    db: DatabaseManager,
    haplotype_name: str,
    species_id: int = None
) -> Dict[str, Any]:
    """Get presence statistics for an allele from artifact summary rows.

    When species_id is provided, numerator and denominator are scoped to that
    species so the result matches the Haplotype Explorer frequency definition.
    """
    summary_query = """
        SELECT
            mps.present_count,
            mps.total_count,
            mps.frequency
        FROM microhaplotype_presence_summary mps
        JOIN microhaplotypes m ON m.id = mps.microhaplotype_id
        WHERE m.haplotype_name = ?
          AND mps.entity_type = 'sample'
    """
    params: List[Any] = [haplotype_name]
    if species_id:
        summary_query += " AND mps.species_id = ?"
        params.append(species_id)
    summary_query += " ORDER BY mps.updated_at DESC"
    summary_rows = db.execute_query(summary_query, tuple(params))
    if summary_rows:
        summary = summary_rows[0]
        total = int(summary.get('total_count') or 0)
        present = int(summary.get('present_count') or 0)
        return {
            'total_samples': total,
            'present_samples': present,
            'absent_samples': max(total - present, 0),
            'presence_frequency': (present / total) if total else 0.0,
        }

    artifact_present = len(_get_entity_ids_for_haplotype_artifacts(db, haplotype_name, "sample"))
    if artifact_present:
        total_query = "SELECT COUNT(*) AS total FROM samples"
        total_params: Tuple[Any, ...] = ()
        if species_id:
            total_query += " WHERE species_id = ?"
            total_params = (species_id,)
        total_rows = db.execute_query(total_query, total_params)
        total = int(total_rows[0].get("total") or 0) if total_rows else 0
        return {
            'total_samples': total,
            'present_samples': artifact_present,
            'absent_samples': max(total - artifact_present, 0),
            'presence_frequency': (artifact_present / total) if total else 0.0,
        }

    return {
        'total_samples': 0,
        'present_samples': 0,
        'absent_samples': 0,
        'presence_frequency': 0.0,
    }



def get_projects_for_allele_presence(db: DatabaseManager,
                                    haplotype_name: str) -> List[Dict[str, Any]]:
    """Get projects with presence=1 for an allele from project artifacts."""
    project_ids = _get_entity_ids_for_haplotype_artifacts(db, haplotype_name, "project")
    if not project_ids:
        return []

    results: List[Dict[str, Any]] = []
    for chunk in _chunks(project_ids):
        placeholders = ",".join(["?"] * len(chunk))
        project_query = f"""
            SELECT
                p.id,
                p.project_code,
                p.project_name,
                p.pi_name,
                p.pi_email,
                p.pi_institution,
                p.pi_department,
                p.description,
                p.start_date
            FROM projects p
            WHERE p.id IN ({placeholders})
            ORDER BY p.project_code
        """
        results.extend(db.execute_query(project_query, tuple(chunk)))
    return sorted(results, key=lambda r: r.get("project_code") or "")


def get_projects_for_sample_presence(db: DatabaseManager,
                                     haplotype_name: str) -> List[Dict[str, Any]]:
    """Get projects linked to a microhaplotype through sample artifacts."""
    sample_ids = _get_entity_ids_for_haplotype_artifacts(db, haplotype_name, "sample")
    if not sample_ids:
        return []

    aggregated = {}
    for chunk in _chunks(sample_ids):
        placeholders = ",".join(["?"] * len(chunk))
        project_query = f"""
            SELECT
                p.id AS project_id,
                p.project_code,
                p.project_name,
                p.pi_name,
                p.pi_email,
                p.pi_institution,
                p.pi_department,
                p.description,
                p.start_date,
                COUNT(DISTINCT s.id) as samples_with_haplotype
            FROM samples s
            JOIN projects p ON s.project_id = p.id
            WHERE s.id IN ({placeholders})
            GROUP BY p.id, p.project_code, p.project_name,
                     p.pi_name, p.pi_email, p.pi_institution,
                     p.pi_department, p.description, p.start_date
        """
        for row in db.execute_query(project_query, tuple(chunk)):
            pid = int(row["project_id"])
            count = int(row.get("samples_with_haplotype") or 0)
            if pid in aggregated:
                aggregated[pid]["samples_with_haplotype"] += count
            else:
                aggregated[pid] = {**dict(row), "samples_with_haplotype": count}

    return sorted(
        aggregated.values(),
        key=lambda r: (-int(r.get("samples_with_haplotype") or 0), r.get("project_code") or ""),
    )


_DAL_PATTERN = re.compile(r"DAl(\d{2})-(\d+)")


def _get_species_project_descriptions(
    db: DatabaseManager, species_id: int
) -> List[Dict[str, Any]]:
    """Return project id + description for every project with samples in the species."""
    query = """
        SELECT DISTINCT p.id AS project_id, p.description
        FROM samples s
        JOIN projects p ON s.project_id = p.id
        WHERE s.species_id = ?
    """
    return db.execute_query(query, (species_id,))


def _parse_dal_key(description: Optional[str]) -> Optional[Tuple[int, int]]:
    """Extract (year, order_number) from a genotyping_source embedded in description."""
    if not description:
        return None
    for part in description.split(";"):
        part = part.strip()
        if part.lower().startswith("genotyping_source="):
            source = part.split("=", 1)[1].strip()
            m = _DAL_PATTERN.search(source)
            if m:
                return int(m.group(1)), int(m.group(2))
    return None


def _build_dal_sort_expr(
    project_rows: List[Dict[str, Any]], col: str = "ss.project_id"
) -> str:
    """Build a Microsoft SQL Server CASE expression that orders projects by DAl ID.

    Projects with parseable DAl IDs sort first (year ASC, order ASC).
    Non-parseable projects sort last (by project_id ASC as tiebreaker).
    Falls back to the bare column name when *project_rows* is empty.
    """
    if not project_rows:
        return col

    parseable = []
    non_parseable = []
    for row in project_rows:
        pid = row["project_id"]
        key = _parse_dal_key(row.get("description"))
        if key:
            parseable.append((key, pid))
        else:
            non_parseable.append(pid)

    parseable.sort()
    non_parseable.sort()

    ordered = [pid for (_key, pid) in parseable] + non_parseable

    if len(ordered) <= 1:
        return col

    whens = " ".join(
        f"WHEN {pid} THEN {pos}" for pos, pid in enumerate(ordered, start=1)
    )
    return f"CASE {col} {whens} ELSE {len(ordered) + 1} END"


def get_microhaplotype_accumulation_data(
    db: DatabaseManager,
    species_id: int,
    max_result_points: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Get compact accumulation-series data from lookup artifacts.

    The result is ordered by DAl/DArT genotyping source then entity, and
    contains:
    - sample_index: 1-based order in the cumulative curve
    - project_id/project_name: project for that sample/project entity
    - cumulative_unique_microhaplotypes: cumulative discovered microhaplotypes

    Sample-level presence drives the sample accumulation curve. Some imports
    only have project-level presence matrices, so include project lookup rows
    for projects that do not have species-matched sample rows.
    """
    samples_query = """
        SELECT
            s.id AS sample_id,
            s.sample_code,
            p.id AS project_id,
            p.project_name,
            p.pi_institution,
            p.description
        FROM samples s
        JOIN projects p ON s.project_id = p.id
        WHERE s.species_id = ?
    """
    sample_rows = db.execute_query(samples_query, (species_id,))

    sample_project_ids = {
        int(row["project_id"])
        for row in sample_rows
        if row.get("project_id") is not None
    }

    artifact_rows = db.execute_query(
        """
        WITH ranked_artifacts AS (
            SELECT
                artifact_path,
                entity_type,
                ROW_NUMBER() OVER (
                    PARTITION BY entity_type, source_path, project_id
                    ORDER BY created_at DESC, id DESC
                ) AS artifact_rank
            FROM presence_artifacts
            WHERE species_id = ?
              AND entity_type IN ('sample_lookup', 'project_lookup')
        )
        SELECT artifact_path, entity_type
        FROM ranked_artifacts
        WHERE artifact_rank = 1
        """,
        (species_id,),
    )
    sample_artifact_paths = [
        row["artifact_path"]
        for row in artifact_rows
        if row.get("artifact_path") and row.get("entity_type") == "sample_lookup"
    ]
    project_artifact_paths = [
        row["artifact_path"]
        for row in artifact_rows
        if row.get("artifact_path") and row.get("entity_type") == "project_lookup"
    ]
    if not sample_artifact_paths and not project_artifact_paths:
        return []

    def entity_sort_key(row: Dict[str, Any]) -> tuple:
        dal_key = _parse_dal_key(row.get("description"))
        return (
            0 if dal_key else 1,
            dal_key or (9999, 999999999),
            int(row.get("project_id") or 0),
            int(row.get("sample_id") or 0),
        )

    loaded_sample_artifacts = []
    for artifact_path in sample_artifact_paths:
        try:
            loaded_sample_artifacts.append(load_lookup_artifact(artifact_path))
        except Exception:
            continue
    loaded_project_artifacts = []
    for artifact_path in project_artifact_paths:
        try:
            loaded_project_artifacts.append(load_lookup_artifact(artifact_path))
        except Exception:
            continue

    if not loaded_sample_artifacts and not loaded_project_artifacts:
        return []

    project_lookup_ids = sorted(
        {
            int(project_id)
            for artifact in loaded_project_artifacts
            for project_id in artifact["entity_ids"].tolist()
        }
    )
    project_rows: List[Dict[str, Any]] = []
    for chunk in _chunks(project_lookup_ids):
        placeholders = ",".join(["?"] * len(chunk))
        project_rows.extend(
            db.execute_query(
                f"""
                SELECT
                    p.id AS project_id,
                    p.project_name,
                    p.pi_institution,
                    p.description
                FROM projects p
                WHERE p.id IN ({placeholders})
                """,
                tuple(chunk),
            )
        )
    project_only_rows = [
        row
        for row in project_rows
        if row.get("project_id") is not None
        and int(row["project_id"]) not in sample_project_ids
    ]
    if not sample_rows and not project_only_rows:
        return []

    loaded_artifacts = loaded_sample_artifacts + loaded_project_artifacts
    first_axis = loaded_artifacts[0]["microhaplotype_ids"]
    first_axis_count = int(loaded_artifacts[0]["microhaplotype_count"])
    can_use_packed_accumulation = all(
        int(artifact["microhaplotype_count"]) == first_axis_count
        and np.array_equal(artifact["microhaplotype_ids"], first_axis)
        for artifact in loaded_artifacts
    )
    packed_row_width = None
    if can_use_packed_accumulation:
        packed_presence = loaded_artifacts[0]["packed_presence"]
        packed_row_width = packed_presence.shape[1]

    all_project_ids = {
        int(row["project_id"])
        for row in sample_rows + project_only_rows
        if row.get("project_id") is not None
    }
    contact_details_by_project: Dict[int, List[Tuple[str, str]]] = defaultdict(list)
    if all_project_ids:
        placeholders = ",".join(["?"] * len(all_project_ids))
        contact_rows = db.execute_query(
            f"""
            SELECT
                pc.project_id,
                c.institution,
                c.location
            FROM project_contacts pc
            JOIN contacts c ON c.id = pc.contact_id
            WHERE pc.project_id IN ({placeholders})
              AND c.institution IS NOT NULL
              AND c.institution <> ''
            """,
            tuple(sorted(all_project_ids)),
        )
        for contact_row in contact_rows:
            project_id = contact_row.get("project_id")
            institution = (contact_row.get("institution") or "").strip()
            location = (contact_row.get("location") or "").strip()
            if project_id is not None and institution:
                contact_details_by_project[int(project_id)].append((institution, location))

    def institution_location_labels(row: Dict[str, Any]) -> Tuple[str, str, str]:
        details = []
        project_id = row.get("project_id")
        if project_id is not None:
            details.extend(contact_details_by_project.get(int(project_id), []))
        pi_institution = (row.get("pi_institution") or "").strip()
        if pi_institution and not details:
            details.append((pi_institution, ""))

        unique_details = []
        seen = set()
        for institution, location in details:
            key = (institution.casefold(), location.casefold())
            if key not in seen:
                seen.add(key)
                unique_details.append((institution, location))

        if not unique_details:
            return "Unknown institution", "", "Unknown institution"

        institutions = []
        institution_keys = set()
        locations = []
        location_keys = set()
        for institution, location in unique_details:
            institution_key = institution.casefold()
            if institution_key not in institution_keys:
                institution_keys.add(institution_key)
                institutions.append(institution)
            if location:
                location_key = location.casefold()
                if location_key not in location_keys:
                    location_keys.add(location_key)
                    locations.append(location)

        if len(institutions) <= 2:
            institution_label = " / ".join(institutions)
        else:
            institution_label = f"{institutions[0]} + {len(institutions) - 1} more"

        if len(locations) <= 2:
            location_label = " / ".join(locations)
        else:
            location_label = f"{locations[0]} + {len(locations) - 1} more"

        group_label = institution_label
        if len(institutions) == 1 and location_label:
            group_label = f"{institution_label} ({location_label})"

        return institution_label, location_label, group_label

    ordered_entities = sorted(
        [
            {
                "entity_type": "sample",
                "entity_id": int(row["sample_id"]),
                "project_id": row.get("project_id"),
                "project_name": row.get("project_name"),
                "pi_institution": row.get("pi_institution"),
                "description": row.get("description"),
                "sample_id": row.get("sample_id"),
            }
            for row in sample_rows
            if row.get("sample_id") is not None
        ]
        + [
            {
                "entity_type": "project",
                "entity_id": int(row["project_id"]),
                "project_id": row.get("project_id"),
                "project_name": row.get("project_name"),
                "pi_institution": row.get("pi_institution"),
                "description": row.get("description"),
                "sample_id": 0,
            }
            for row in project_only_rows
        ],
        key=entity_sort_key,
    )

    seen_microhaplotypes = set()
    results: List[Dict[str, Any]] = []
    output_indices = None
    if (
        max_result_points
        and max_result_points > 0
        and len(ordered_entities) > max_result_points
    ):
        output_indices = set(
            int(index)
            for index in np.unique(
                np.linspace(0, len(ordered_entities) - 1, max_result_points, dtype=int)
            ).tolist()
        )

    if packed_row_width is not None:
        ordered_packed_rows = np.zeros(
            (len(ordered_entities), packed_row_width),
            dtype=loaded_artifacts[0]["packed_presence"].dtype,
        )
        for ordered_index, row in enumerate(ordered_entities):
            entity_id = int(row["entity_id"])
            artifacts = (
                loaded_sample_artifacts
                if row["entity_type"] == "sample"
                else loaded_project_artifacts
            )
            for artifact in artifacts:
                row_idx = artifact["entity_index"].get(entity_id)
                if row_idx is not None:
                    np.bitwise_or(
                        ordered_packed_rows[ordered_index],
                        artifact["packed_presence"][row_idx],
                        out=ordered_packed_rows[ordered_index],
                    )

        cumulative_rows = np.bitwise_or.accumulate(ordered_packed_rows, axis=0)
        cumulative_counts = _BYTE_POPCOUNT[cumulative_rows].sum(axis=1).astype(np.int64)

        for ordered_index, row in enumerate(ordered_entities):
            if output_indices is not None and ordered_index not in output_indices:
                continue
            institution_label, location_label, group_label = institution_location_labels(row)
            results.append(
                {
                    "sample_index": ordered_index + 1,
                    "project_id": row.get("project_id"),
                    "project_name": row.get("project_name"),
                    "institution_label": institution_label,
                    "institution_location": location_label,
                    "institution_group_label": group_label,
                    "cumulative_unique_microhaplotypes": int(cumulative_counts[ordered_index]),
                }
            )

        return results

    for ordered_index, row in enumerate(ordered_entities):
        entity_id = int(row["entity_id"])
        artifacts = (
            loaded_sample_artifacts
            if row["entity_type"] == "sample"
            else loaded_project_artifacts
        )
        for artifact in artifacts:
            seen_microhaplotypes.update(
                read_microhaplotype_ids_from_loaded_lookup(artifact, entity_id)
            )
        if output_indices is not None and ordered_index not in output_indices:
            continue
        cumulative_unique_count = len(seen_microhaplotypes)
        institution_label, location_label, group_label = institution_location_labels(row)
        results.append(
            {
                "sample_index": ordered_index + 1,
                "project_id": row.get("project_id"),
                "project_name": row.get("project_name"),
                "institution_label": institution_label,
                "institution_location": location_label,
                "institution_group_label": group_label,
                "cumulative_unique_microhaplotypes": cumulative_unique_count,
            }
        )

    return results


def get_microhaplotype_project_sharing_data(
    db: DatabaseManager,
    species_id: int,
    max_intersections: int = 24,
    selected_group_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Summarize microhaplotype sharing intersections across selected groups.

    Returns UpSet-style intersection counts derived from project lookup artifacts.
    Groups include Remaining Locations, Validation, and institution/location programs.
    """
    if not species_id:
        return {
            "owner_groups": [],
            "available_owner_groups": [],
            "projects": [],
            "intersections": [],
        }

    artifact_rows = db.execute_query(
        """
        SELECT artifact_path
        FROM presence_artifacts
        WHERE species_id = ?
          AND entity_type = 'project_lookup'
        ORDER BY created_at DESC
        """,
        (species_id,),
    )
    artifact_paths = [
        row["artifact_path"]
        for row in artifact_rows
        if row.get("artifact_path")
    ]
    if not artifact_paths:
        return {
            "owner_groups": [],
            "available_owner_groups": [],
            "projects": [],
            "intersections": [],
        }

    loaded_artifacts = []
    for artifact_path in artifact_paths:
        try:
            loaded_artifacts.append(load_lookup_artifact(artifact_path))
        except Exception:
            continue
    if not loaded_artifacts:
        return {
            "owner_groups": [],
            "available_owner_groups": [],
            "projects": [],
            "intersections": [],
        }

    microhaplotype_projects = defaultdict(set)
    project_ids_seen = set()
    for artifact in loaded_artifacts:
        entity_ids = artifact["entity_ids"]
        microhaplotype_ids = artifact["microhaplotype_ids"]
        microhaplotype_count = int(artifact["microhaplotype_count"])
        packed_presence = artifact["packed_presence"]

        for row_idx, raw_project_id in enumerate(entity_ids.tolist()):
            project_id = int(raw_project_id)
            project_ids_seen.add(project_id)
            bits = np.unpackbits(
                packed_presence[row_idx],
                bitorder="little",
            )[:microhaplotype_count]
            present_positions = np.flatnonzero(bits)
            for pos in present_positions.tolist():
                microhaplotype_projects[int(microhaplotype_ids[pos])].add(project_id)

    if not project_ids_seen or not microhaplotype_projects:
        return {
            "owner_groups": [],
            "available_owner_groups": [],
            "projects": [],
            "intersections": [],
        }

    project_rows: List[Dict[str, Any]] = []
    for chunk in _chunks(sorted(project_ids_seen)):
        project_placeholders = ",".join(["?"] * len(chunk))
        project_rows.extend(
            db.execute_query(
                f"""
                SELECT
                    p.id AS project_id,
                    p.project_name,
                    p.pi_institution,
                    p.description
                FROM projects p
                WHERE p.id IN ({project_placeholders})
                """,
                tuple(chunk),
            )
        )
    project_meta = {
        int(row["project_id"]): row
        for row in project_rows
        if row.get("project_id") is not None
    }

    contact_details_by_project: Dict[int, List[Tuple[str, str]]] = defaultdict(list)
    for chunk in _chunks(sorted(project_ids_seen)):
        placeholders = ",".join(["?"] * len(chunk))
        contact_rows = db.execute_query(
            f"""
            SELECT
                pc.project_id,
                c.institution,
                c.location
            FROM project_contacts pc
            JOIN contacts c ON c.id = pc.contact_id
            WHERE pc.project_id IN ({placeholders})
              AND c.institution IS NOT NULL
              AND c.institution <> ''
            """,
            tuple(chunk),
        )
        for contact_row in contact_rows:
            project_id = contact_row.get("project_id")
            institution = (contact_row.get("institution") or "").strip()
            location = (contact_row.get("location") or "").strip()
            if project_id is not None and institution:
                contact_details_by_project[int(project_id)].append((institution, location))
    def program_group_id(institution: str, location: str) -> str:
        institution_slug = re.sub(r"[^a-z0-9]+", "-", institution.casefold()).strip("-")
        location_slug = re.sub(r"[^a-z0-9]+", "-", location.casefold()).strip("-")
        return f"program:{institution_slug or 'unknown'}:{location_slug or 'unknown-location'}"

    group_catalog = [
        {
            "group_id": "validation",
            "label": "Validation",
            "owner_name": "Validation",
            "kind": "preset",
        },
        {
            "group_id": "all",
            "label": "Remaining Locations",
            "owner_name": "Remaining Locations",
            "kind": "preset",
        },
    ]
    groups_by_id = {group["group_id"]: group for group in group_catalog}
    program_group_ids_by_project: Dict[int, List[str]] = defaultdict(list)

    for project_id in sorted(project_ids_seen):
        meta = project_meta.get(project_id, {})
        details = contact_details_by_project.get(project_id, [])
        if not details:
            pi_institution = (meta.get("pi_institution") or "").strip()
            if pi_institution:
                details = [(pi_institution, "")]

        seen_details = set()
        for institution, location in details:
            key = (institution.casefold(), location.casefold())
            if key in seen_details:
                continue
            seen_details.add(key)
            group_id = program_group_id(institution, location)
            program_group_ids_by_project[project_id].append(group_id)
            if group_id not in groups_by_id:
                label = institution if not location else f"{institution} ({location})"
                groups_by_id[group_id] = {
                    "group_id": group_id,
                    "label": label,
                    "owner_name": label,
                    "institution": institution,
                    "location": location,
                    "kind": "program",
                }
                group_catalog.append(groups_by_id[group_id])

    program_groups = [group for group in group_catalog if group.get("kind") == "program"]
    program_groups.sort(key=lambda group: group["label"].casefold())
    group_catalog = [
        groups_by_id["validation"],
        *program_groups,
        groups_by_id["all"],
    ]
    group_order = {group["group_id"]: index for index, group in enumerate(group_catalog)}

    def base_group_ids_for_project(project_id: int) -> List[str]:
        meta = project_meta.get(project_id, {})
        project_name = (meta.get("project_name") or f"Project {project_id}").strip()
        group_ids = []
        if project_name.lower() == "validation":
            group_ids.append("validation")
        group_ids.extend(program_group_ids_by_project.get(project_id, []))
        return sorted(set(group_ids), key=lambda group_id: group_order.get(group_id, 999999))

    default_group_ids = ["validation"]
    if len(program_groups) >= 2:
        default_group_ids.extend(
            group["group_id"] for group in random.sample(program_groups, 2)
        )
    elif program_groups:
        default_group_ids.extend(group["group_id"] for group in program_groups)
    else:
        default_group_ids.append("all")

    requested_group_ids = [
        group_id
        for group_id in (selected_group_ids or default_group_ids)
        if group_id in groups_by_id
    ]
    if not requested_group_ids:
        requested_group_ids = default_group_ids
    selected_group_set = set(requested_group_ids)
    owner_groups = [
        group
        for group in group_catalog
        if group["group_id"] in selected_group_set
    ]
    remaining_group_id = "all"
    selected_specific_group_ids = selected_group_set - {remaining_group_id}

    def group_ids_for_project(project_id: int) -> List[str]:
        base_group_ids = base_group_ids_for_project(project_id)
        group_ids = [
            group_id
            for group_id in base_group_ids
            if group_id in selected_specific_group_ids
        ]
        project_program_group_ids = set(program_group_ids_by_project.get(project_id, []))
        has_unselected_program = any(
            group_id not in selected_specific_group_ids
            for group_id in project_program_group_ids
        )
        has_only_unclassified_nonvalidation_project = (
            not project_program_group_ids
            and "validation" not in base_group_ids
        )
        if (
            remaining_group_id in selected_group_set
            and (has_unselected_program or has_only_unclassified_nonvalidation_project)
        ):
            group_ids.append(remaining_group_id)
        return sorted(set(group_ids), key=lambda group_id: group_order.get(group_id, 999999))

    pattern_counts = Counter(
        tuple(
            sorted(
                {
                    group_id
                    for project_id in project_ids
                    for group_id in group_ids_for_project(project_id)
                    if group_id in selected_group_set
                },
                key=lambda group_id: group_order.get(group_id, 999999),
            )
        )
        for project_ids in microhaplotype_projects.values()
        if project_ids
    )
    pattern_counts.pop((), None)
    intersections = []
    for group in owner_groups:
        pattern_counts.setdefault((group["group_id"],), 0)

    for group_ids, count in pattern_counts.items():
        if not group_ids:
            continue
        group_count = len(group_ids)
        if group_count == len(owner_groups):
            category = "common"
        elif group_count == 1:
            category = "private"
        else:
            category = "rare"
        intersections.append(
            {
                "group_ids": list(group_ids),
                "project_ids": list(group_ids),
                "project_count": group_count,
                "microhaplotype_count": int(count),
                "category": category,
            }
        )

    intersections.sort(
        key=lambda row: (
            {"common": 0, "rare": 1, "private": 2}.get(row["category"], 3),
            -row["project_count"],
            -row["microhaplotype_count"],
            [group_order.get(group_id, 999999) for group_id in row["group_ids"]],
        )
    )
    if max_intersections and max_intersections > 0:
        required_singletons = {
            (group["group_id"],)
            for group in owner_groups
        }
        selected_rows = intersections[:max_intersections]
        selected_keys = {tuple(row["group_ids"]) for row in selected_rows}
        missing_singletons = [
            row
            for row in intersections[max_intersections:]
            if tuple(row["group_ids"]) in required_singletons
            and tuple(row["group_ids"]) not in selected_keys
        ]
        if missing_singletons:
            selected_rows = selected_rows + missing_singletons
            selected_rows.sort(
                key=lambda row: (
                    {"common": 0, "rare": 1, "private": 2}.get(row["category"], 3),
                    -row["project_count"],
                    -row["microhaplotype_count"],
                    [group_order.get(group_id, 999999) for group_id in row["group_ids"]],
                )
            )
        intersections = selected_rows

    return {
        "owner_groups": owner_groups,
        "available_owner_groups": group_catalog,
        "default_group_ids": default_group_ids,
        "projects": owner_groups,
        "intersections": intersections,
    }


def get_contacts_for_projects(db: DatabaseManager,
                              project_ids: List[int]) -> List[Dict[str, Any]]:
    """Get contacts linked to a set of projects via the project_contacts table."""
    if not project_ids:
        return []
    placeholders = ','.join('?' * len(project_ids))
    query = f"""
        SELECT DISTINCT
            pc.project_id,
            c.full_name,
            c.email,
            c.institution,
            c.location
        FROM project_contacts pc
        JOIN contacts c ON pc.contact_id = c.id
        WHERE pc.project_id IN ({placeholders})
        ORDER BY pc.project_id, c.full_name
    """
    return db.execute_query(query, tuple(project_ids))
