"""SQL queries for HaploSearch features"""

import re
from typing import List, Dict, Any, Optional, Tuple
from database.db_manager import DatabaseManager

_PROJECT_PREFIX_RE = re.compile(r'^(P\d+)')
_JUNK_PROJECT_NAMES = frozenset({'count', '12plates', '2plates'})


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
        # Supports both presence table (allele_sample_presence) and association table (microhaplotype_samples).
        query += """
            AND (
                EXISTS (
                    SELECT 1
                    FROM allele_sample_presence asp
                    JOIN samples s ON s.id = asp.sample_id
                    WHERE asp.microhaplotype_id = m.id
                      AND s.sample_code LIKE ?
                )
                OR EXISTS (
                    SELECT 1
                    FROM microhaplotype_samples ms
                    JOIN samples s2 ON s2.id = ms.sample_id
                    WHERE ms.microhaplotype_id = m.id
                      AND s2.sample_code LIKE ?
                )
            )
        """
        sample_pattern = f"%{sample_filter}%"
        params.extend([sample_pattern, sample_pattern])

    if min_frequency is not None:
        query += " AND m.frequency >= ?"
        params.append(float(min_frequency))

    if max_frequency is not None:
        query += " AND m.frequency <= ?"
        params.append(float(max_frequency))

    # "Missing" sample context (species has no samples) should not be treated as
    # true zero frequency when users filter specifically for 0.
    if (
        min_frequency is not None
        and float(min_frequency) <= 0.0
    ):
        query += " AND EXISTS (SELECT 1 FROM samples s3 WHERE s3.species_id = sp.id)"

    query += " ORDER BY m.haplotype_name"

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

    all_species_projects_query = """
        SELECT p.id, p.project_code, p.project_name, p.pi_name
        FROM projects p
        WHERE EXISTS (SELECT 1 FROM samples s WHERE s.project_id = p.id AND s.species_id = ?)
    """
    params = [species_id]
    try:
        if db.table_exists('allele_project_presence'):
            all_species_projects_query += """
                UNION
                SELECT p2.id, p2.project_code, p2.project_name, p2.pi_name
                FROM projects p2
                WHERE EXISTS (
                    SELECT 1 FROM allele_project_presence app
                    JOIN microhaplotypes m ON app.microhaplotype_id = m.id
                    JOIN markers mk ON m.marker_id = mk.id
                    JOIN chromosomes c ON mk.chromosome_id = c.id
                    WHERE app.project_id = p2.id AND c.species_id = ?
                )
            """
            params.append(species_id)
    except Exception:
        pass
    all_proj_rows = db.execute_query(all_species_projects_query, tuple(params))
    deduped = _deduplicate_projects(all_proj_rows)
    project_count = len(deduped)

    avg_alleles = round(microhaplotype_count / marker_count, 1) if marker_count else 0.0

    rare_query = """
        SELECT COUNT(*) AS rare_count
        FROM microhaplotypes m
        JOIN markers mk ON m.marker_id = mk.id
        JOIN chromosomes c ON mk.chromosome_id = c.id
        WHERE c.species_id = ? AND m.sample_count <= 1
    """
    rare_rows = db.execute_query(rare_query, (species_id,))
    rare_alleles = (rare_rows[0]['rare_count'] if rare_rows else 0) or 0

    return {
        'species_label': species_label,
        'marker_count': marker_count,
        'microhaplotype_count': microhaplotype_count,
        'avg_alleles_per_marker': avg_alleles,
        'sample_count': sample_count,
        'project_count': project_count,
        'rare_alleles': rare_alleles,
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
    """Get all samples with presence for an allele (haplotype_name)"""
    query = """
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
        FROM allele_sample_presence asp
        JOIN microhaplotypes m ON asp.microhaplotype_id = m.id
        JOIN samples s ON asp.sample_id = s.id
        JOIN projects p ON s.project_id = p.id
        JOIN species sp ON s.species_id = sp.id
        WHERE m.haplotype_name = ?
        ORDER BY p.project_code, s.sample_code
    """
    return db.execute_query(query, (haplotype_name,))


def get_alleles_for_sample(db: DatabaseManager, sample_code: str) -> List[Dict[str, Any]]:
    """Get all alleles present in a sample"""
    query = """
        SELECT
            m.haplotype_name,
            1 as presence,
            m.haplotype_sequence,
            m.frequency,
            mk.marker_id,
            sp.name as species_name
        FROM allele_sample_presence asp
        JOIN microhaplotypes m ON asp.microhaplotype_id = m.id
        JOIN samples s ON asp.sample_id = s.id
        JOIN markers mk ON m.marker_id = mk.id
        JOIN chromosomes c ON mk.chromosome_id = c.id
        JOIN species sp ON c.species_id = sp.id
        WHERE s.sample_code = ?
        ORDER BY mk.marker_id, m.haplotype_name
    """
    return db.execute_query(query, (sample_code,))


def get_presence_statistics(
    db: DatabaseManager,
    haplotype_name: str,
    species_id: int = None
) -> Dict[str, Any]:
    """Get presence statistics for an allele.

    When species_id is provided, numerator and denominator are scoped to that
    species so the result matches the Haplotype Explorer frequency definition.
    """
    # Get present count
    query = """
        SELECT COUNT(*) as present_samples
        FROM allele_sample_presence asp
        JOIN microhaplotypes m ON asp.microhaplotype_id = m.id
        JOIN samples s ON asp.sample_id = s.id
        WHERE m.haplotype_name = ?
    """
    params = [haplotype_name]
    if species_id:
        query += " AND s.species_id = ?"
        params.append(species_id)

    results = db.execute_query(query, tuple(params))
    present_samples = results[0]['present_samples'] if results else 0
    
    # Get total samples count
    total_query = "SELECT COUNT(*) as total FROM samples"
    total_params = ()
    if species_id:
        total_query += " WHERE species_id = ?"
        total_params = (species_id,)
    total_results = db.execute_query(total_query, total_params)
    total_samples = total_results[0]['total'] if total_results else 0
    
    absent_samples = total_samples - present_samples
    presence_frequency = present_samples / total_samples if total_samples > 0 else 0.0
    
    return {
        'total_samples': total_samples,
        'present_samples': present_samples,
        'absent_samples': absent_samples,
        'presence_frequency': presence_frequency
    }



def get_projects_for_allele_presence(db: DatabaseManager,
                                    haplotype_name: str) -> List[Dict[str, Any]]:
    """Get projects with presence=1 for an allele via allele_project_presence.

    Returns an empty list if the table does not exist (backwards compatible with older DBs).
    """
    try:
        if not db.table_exists('allele_project_presence'):
            return []
    except Exception:
        return []

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
            p.start_date
        FROM allele_project_presence app
        JOIN microhaplotypes m ON app.microhaplotype_id = m.id
        JOIN projects p ON app.project_id = p.id
        WHERE m.haplotype_name = ?
        ORDER BY p.project_code
    """
    return db.execute_query(query, (haplotype_name,))


def get_projects_for_sample_presence(db: DatabaseManager,
                                     haplotype_name: str) -> List[Dict[str, Any]]:
    """Get projects linked to a microhaplotype via allele_sample_presence -> samples -> projects."""
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
            COUNT(DISTINCT s.id) as samples_with_haplotype
        FROM allele_sample_presence asp
        JOIN microhaplotypes m ON asp.microhaplotype_id = m.id
        JOIN samples s ON asp.sample_id = s.id
        JOIN projects p ON s.project_id = p.id
        WHERE m.haplotype_name = ?
        GROUP BY p.id, p.project_code, p.project_name,
                 p.pi_name, p.pi_email, p.pi_institution,
                 p.pi_department, p.description, p.start_date
        ORDER BY samples_with_haplotype DESC
    """
    return db.execute_query(query, (haplotype_name,))


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
    db: DatabaseManager, species_id: int
) -> List[Dict[str, Any]]:
    """Get compact accumulation-series data (one row per sample).

    The result is ordered by DAl/DArT genotyping source then sample, and
    contains:
    - sample_index: 1-based order in the cumulative curve
    - project_id/project_name: project for that sample
    - cumulative_unique_microhaplotypes: cumulative discovered microhaplotypes

    Tries ``allele_sample_presence`` first; falls back to
    ``microhaplotype_samples`` when the presence table is empty.
    """
    project_rows = _get_species_project_descriptions(db, species_id)
    project_sort_expr = _build_dal_sort_expr(project_rows)

    query_template = """
        WITH species_samples AS (
            SELECT DISTINCT
                assoc.sample_id,
                p.id AS project_id,
                p.project_name
            FROM {table} assoc
            JOIN microhaplotypes m ON assoc.microhaplotype_id = m.id
            JOIN markers mk ON m.marker_id = mk.id
            JOIN chromosomes c ON mk.chromosome_id = c.id
            JOIN samples s ON s.id = assoc.sample_id
            JOIN projects p ON s.project_id = p.id
            WHERE c.species_id = ?
        ),
        ordered_samples AS (
            SELECT
                ss.sample_id,
                ss.project_id,
                ss.project_name,
                ROW_NUMBER() OVER (ORDER BY {project_sort_expr}, ss.sample_id) AS sample_index
            FROM species_samples ss
        ),
        first_seen AS (
            SELECT
                assoc.microhaplotype_id,
                MIN(os.sample_index) AS first_sample_index
            FROM {table} assoc
            JOIN ordered_samples os ON os.sample_id = assoc.sample_id
            GROUP BY assoc.microhaplotype_id
        ),
        new_per_sample AS (
            SELECT
                first_sample_index AS sample_index,
                COUNT(*) AS new_count
            FROM first_seen
            GROUP BY first_sample_index
        )
        SELECT
            os.sample_index,
            os.project_id,
            os.project_name,
            SUM(COALESCE(nps.new_count, 0)) OVER (
                ORDER BY os.sample_index
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS cumulative_unique_microhaplotypes
        FROM ordered_samples os
        LEFT JOIN new_per_sample nps ON os.sample_index = nps.sample_index
        ORDER BY os.sample_index
    """

    fmt = dict(table="allele_sample_presence", project_sort_expr=project_sort_expr)
    query = query_template.format(**fmt)
    results = db.execute_query(query, (species_id,))

    if not results or all(
        (row.get("cumulative_unique_microhaplotypes") or 0) == 0 for row in results
    ):
        fmt["table"] = "microhaplotype_samples"
        query = query_template.format(**fmt)
        results = db.execute_query(query, (species_id,))

    return results


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
