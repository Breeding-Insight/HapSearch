#!/usr/bin/env python3
"""Import allele-project presence/absence data into HaploSearch database.

Expected CSV/TSV format (matrix):
- First column: AlleleID (haplotype_name, e.g., chr1.1_000194324|Ref_0001)
- Optional second column: CloneID (ignored)
- Remaining columns: Project headers (see below)
- Cell values: 1/0 (or 1.0/0.0, true/false, yes/no)

Project header convention (example):
  P01_Debby_Zhanyou_digestibility_16plates_DAl21-6679

This importer:
- Stores compressed allele-to-project and project-to-allele bitmap artifacts
- Auto-creates missing projects using canonical project_code from mapping
- Attempts a best-effort parse of owner/informal name/genotyping source for project fields
"""

import os
import sys
import time
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager
from database.presence_artifacts import (
    counts_by_microhaplotype,
    ensure_presence_artifact_schema,
    record_presence_artifact,
    upsert_presence_summary,
    write_presence_bitmap_artifact,
    write_presence_lookup_artifact,
)
from scripts.presence_metadata import (
    genotyping_sources_match,
    get_mapping_for_project_code,
    get_or_upsert_project,
    link_project_contacts,
    load_owner_contacts,
    load_project_mapping,
    normalize_project_code,
    parse_project_header,
    read_matrix,
    resolve_project_record,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROJECT_MAPPING_PATH = os.path.join(
    _REPO_ROOT, "data", "presence_absence", "HapSearch_mapping.csv"
)
DEFAULT_OWNER_CONTACTS_PATH = os.path.join(
    _REPO_ROOT, "data", "presence_absence", "HapSearch_owner_contacts.csv"
)
_NON_PROJECT_COLUMN_NAMES = {"presence_count", "presencecount", "count"}


def validate_project_columns_against_mapping(
    project_columns: List[Any],
    mapping_by_project_code: Dict[str, Dict[str, str]],
) -> None:
    """Validate matrix project headers against mapping source of truth."""
    unmapped_project_columns: List[str] = []
    source_mismatch_columns: List[tuple] = []
    for project_header in project_columns:
        header_value = str(project_header).strip()
        if not header_value:
            continue
        mapping_row = get_mapping_for_project_code(header_value, mapping_by_project_code)
        if not mapping_row:
            unmapped_project_columns.append(header_value)
            continue
        parsed = parse_project_header(header_value)
        parsed_source = parsed.get("genotyping_source") or ""
        mapping_source = (mapping_row or {}).get("genotyping_source") or ""
        if parsed_source and mapping_source and not genotyping_sources_match(parsed_source, mapping_source):
            source_mismatch_columns.append((header_value, parsed_source, mapping_source))

    if unmapped_project_columns:
        preview = ", ".join(unmapped_project_columns[:10])
        if len(unmapped_project_columns) > 10:
            preview += ", ..."
        raise ValueError(
            "Project matrix columns must exactly match project_code values in the mapping file. "
            f"Unmapped columns: {preview}. Update HapSearch_mapping.csv (or your mapping input) or fix "
            "the matrix headers."
        )

    if source_mismatch_columns:
        mismatch_lines = [
            f"{header} (header source={parsed_src}, mapping source={mapped_src})"
            for header, parsed_src, mapped_src in source_mismatch_columns[:10]
        ]
        details = "; ".join(mismatch_lines)
        if len(source_mismatch_columns) > 10:
            details += "; ..."
        raise ValueError(
            "Project header DAl/DArT source tokens must match mapping genotyping_source for each project_code. "
            f"Mismatches: {details}"
        )


class ProjectPresenceImporter:
    """Import allele-project presence/absence data from CSV files."""

    def __init__(self):
        self.db = DatabaseManager()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Ensure artifact metadata/summary tables exist."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            ensure_presence_artifact_schema(cursor)

    def import_project_presence(
        self,
        csv_path: str,
        project_mapping_path: str,
        owner_contacts_path: str,
        verbose: bool = True,
        artifact_dir: Optional[str] = None,
    ) -> Dict[str, int]:
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        if verbose:
            print(f"\nImporting project presence data from: {csv_path}", flush=True)
        start_time = time.time()

        mapping_result = load_project_mapping(project_mapping_path)
        contacts_result = load_owner_contacts(owner_contacts_path)
        mapping_by_project_code = mapping_result.by_project_code
        contacts_by_owner = contacts_result.by_owner_name
        missing_owner_contacts: set = set()

        if verbose and mapping_result.missing_optional_columns:
            print(
                "Warning: project mapping optional columns missing; blanks will be used: "
                + ", ".join(mapping_result.missing_optional_columns),
                flush=True,
            )
        if verbose and contacts_result.missing_optional_columns:
            print(
                "Warning: owner contacts optional columns missing; blanks will be used: "
                + ", ".join(contacts_result.missing_optional_columns),
                flush=True,
            )

        df = read_matrix(csv_path)

        if df.shape[1] < 2:
            raise ValueError("File must have at least 2 columns (AlleleID + at least one project column)")

        allele_id_col = df.columns[0]
        remaining_cols = list(df.columns[1:])

        if remaining_cols and str(remaining_cols[0]).strip().lower() in {"cloneid", "clone_id"}:
            candidate_columns = remaining_cols[1:]
        else:
            candidate_columns = remaining_cols

        project_columns = [
            col for col in candidate_columns
            if str(col).strip().lower() not in _NON_PROJECT_COLUMN_NAMES
        ]

        if not project_columns:
            raise ValueError("No project columns detected (expected columns after AlleleID[, CloneID])")

        validate_project_columns_against_mapping(project_columns, mapping_by_project_code)

        if verbose:
            print(f"Found {len(df):,} alleles and {len(project_columns)} projects", flush=True)
            print(
                "Project columns: "
                + ", ".join([str(c) for c in project_columns[:3]])
                + ("..." if len(project_columns) > 3 else ""),
                flush=True,
            )

        imported = 0
        deleted = 0
        created_projects = 0
        updated_projects = 0
        created_contacts = 0
        linked_contacts = 0
        skipped_alleles = 0
        errors = 0

        def chunked(items, size):
            for i in range(0, len(items), size):
                yield items[i:i + size]

        in_clause_chunk = 400

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # --- Phase 1: Resolve projects, contacts, owners ---
            if verbose:
                print("Phase 1/3: Resolving projects and contacts...", flush=True)

            project_id_cache: Dict[str, int] = {}
            for project_header in project_columns:
                ph = str(project_header).strip()
                if not ph or ph in project_id_cache:
                    continue

                parsed = parse_project_header(ph)
                mapping_row = get_mapping_for_project_code(ph, mapping_by_project_code)
                if not mapping_row:
                    raise ValueError(
                        f"Missing mapping row for project column '{ph}'. "
                        "Project columns must map directly to project_code values."
                    )

                owner_names = (mapping_row or {}).get("owner_names") or []
                if not owner_names:
                    mapped_owner = (mapping_row or {}).get("owner_name") or ""
                    owner_names = [mapped_owner] if mapped_owner else []
                for on in owner_names:
                    if on and on.casefold() not in contacts_by_owner:
                        missing_owner_contacts.add(on)

                resolved = resolve_project_record(
                    parsed,
                    mapping_row,
                    contacts_by_owner,
                    forced_project_code=normalize_project_code(mapping_row["project_code"]),
                )
                project_id, was_created, was_project_updated = get_or_upsert_project(cursor, resolved)
                if was_created:
                    created_projects += 1
                elif was_project_updated:
                    updated_projects += 1

                if owner_names:
                    link_stats = link_project_contacts(
                        cursor, project_id, owner_names, contacts_by_owner
                    )
                    created_contacts += link_stats["created_contacts"]
                    linked_contacts += link_stats["linked_contacts"]

                project_id_cache[ph] = project_id

            if verbose:
                print(
                    f"  {len(project_id_cache)} projects resolved "
                    f"({created_projects} created, {updated_projects} updated)",
                    flush=True,
                )

            # --- Phase 2: Bulk-resolve AlleleID -> microhaplotype_id ---
            if verbose:
                print("Phase 2/3: Resolving AlleleID -> microhaplotype_id mappings...", flush=True)

            allele_ids_in_file = df[allele_id_col].astype(str).str.strip().tolist()
            unique_alleles = list(dict.fromkeys(a for a in allele_ids_in_file if a))

            haplotype_id_map: Dict[str, int] = {}
            for allele_chunk in chunked(unique_alleles, in_clause_chunk):
                placeholders = ",".join(["?"] * len(allele_chunk))
                cursor.execute(
                    f"SELECT id, haplotype_name FROM microhaplotypes WHERE haplotype_name IN ({placeholders})",
                    tuple(allele_chunk),
                )
                for row in cursor.fetchall():
                    haplotype_id_map[str(row[1])] = int(row[0])

            skipped_alleles = len(unique_alleles) - len(haplotype_id_map)
            if verbose:
                print(
                    f"  Mapped {len(haplotype_id_map):,}/{len(unique_alleles):,} allele IDs",
                    flush=True,
                )
                if skipped_alleles > 0:
                    missing = [a for a in unique_alleles[:10] if a not in haplotype_id_map]
                    print(f"  Sample missing: {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}", flush=True)

            # --- Phase 3: Build pairs and bulk load via staging table ---
            if verbose:
                print("Phase 3/3: Building presence pairs and bulk loading...", flush=True)

            mh_ids = sorted(haplotype_id_map.values())
            proj_ids = sorted(set(project_id_cache.values()))
            artifact_species_id: Optional[int] = None
            if mh_ids:
                species_ids = set()
                for mh_chunk in chunked(mh_ids, in_clause_chunk):
                    placeholders = ",".join(["?"] * len(mh_chunk))
                    cursor.execute(
                        f"""
                        SELECT DISTINCT c.species_id
                        FROM microhaplotypes m
                        JOIN markers mk ON mk.id = m.marker_id
                        JOIN chromosomes c ON c.id = mk.chromosome_id
                        WHERE m.id IN ({placeholders})
                        """,
                        tuple(mh_chunk),
                    )
                    for row in cursor.fetchall():
                        species_ids.add(int(row[0]))
                if len(species_ids) == 1:
                    artifact_species_id = next(iter(species_ids))

            project_col_list = [str(c).strip() for c in project_columns if str(c).strip()]
            project_id_array = np.array(
                [project_id_cache.get(c, -1) for c in project_col_list], dtype=np.int64
            )
            valid_project_mask = project_id_array > 0

            numeric_presence = df[project_columns].apply(pd.to_numeric, errors="coerce")
            presence_matrix = numeric_presence.fillna(0).eq(1).to_numpy(dtype=bool)
            allele_series = df[allele_id_col].astype(str).str.strip()

            pairs: List[tuple] = []
            for idx, allele_id in enumerate(allele_series):
                if not allele_id:
                    continue
                mh_id = haplotype_id_map.get(allele_id)
                if not mh_id:
                    continue
                present_indices = np.flatnonzero(presence_matrix[idx] & valid_project_mask)
                for pos in present_indices.tolist():
                    pairs.append((mh_id, int(project_id_array[pos])))

            if verbose:
                print(f"  Built {len(pairs):,} presence pairs", flush=True)

            if verbose:
                print("  Writing compressed project presence artifacts...", flush=True)
            ensure_presence_artifact_schema(cursor)
            metadata = write_presence_bitmap_artifact(
                pairs,
                mh_ids,
                proj_ids,
                entity_type="project",
                species_id=artifact_species_id,
                source_path=csv_path,
                output_dir=artifact_dir,
            )
            artifact_id = record_presence_artifact(cursor, metadata)
            lookup_metadata = write_presence_lookup_artifact(
                pairs,
                mh_ids,
                proj_ids,
                entity_type="project_lookup",
                species_id=artifact_species_id,
                source_path=csv_path,
                output_dir=artifact_dir,
            )
            record_presence_artifact(cursor, lookup_metadata)
            if artifact_id and artifact_species_id is not None:
                upsert_presence_summary(
                    cursor,
                    artifact_id=artifact_id,
                    species_id=artifact_species_id,
                    entity_type="project",
                    total_count=len(proj_ids),
                    counts_by_microhaplotype=counts_by_microhaplotype(pairs, mh_ids),
                )
            conn.commit()
            imported = len(pairs)
            if verbose:
                size_mb = (metadata.get("artifact_size_bytes") or 0) / 1024 / 1024
                lookup_size_mb = (lookup_metadata.get("artifact_size_bytes") or 0) / 1024 / 1024
                print(
                    f"  Allele->project artifact: {metadata['artifact_path']} ({size_mb:.2f} MB)",
                    flush=True,
                )
                print(
                    f"  Project->allele artifact: {lookup_metadata['artifact_path']} ({lookup_size_mb:.2f} MB)",
                    flush=True,
                )

        elapsed = time.time() - start_time
        if verbose:
            print(f"\nImport complete! ({elapsed:.1f}s)", flush=True)
            print(f"  Imported: {imported:,} presence records", flush=True)
            print(f"  Deleted stale: {deleted:,} presence records", flush=True)
            print(f"  Created: {created_projects} new projects", flush=True)
            print(f"  Updated project metadata rows: {updated_projects}", flush=True)
            print(f"  Created contacts: {created_contacts}", flush=True)
            print(f"  Linked project-contact associations: {linked_contacts}", flush=True)
            print(f"  Skipped alleles (not found): {skipped_alleles:,}", flush=True)
            if missing_owner_contacts:
                print(
                    "  Warning: missing owner contact rows for: "
                    + ", ".join(sorted(missing_owner_contacts)),
                    flush=True,
                )
            if errors:
                print(f"  Errors: {errors}", flush=True)

        return {
            "imported": imported,
            "deleted": deleted,
            "created_projects": created_projects,
            "updated_projects": updated_projects,
            "created_contacts": created_contacts,
            "linked_contacts": linked_contacts,
            "skipped_alleles": skipped_alleles,
            "unmatched_mapping_sources": 0,
            "missing_owner_contacts": len(missing_owner_contacts),
            "errors": errors,
        }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Import allele-project presence/absence data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("csv_file", help="Path to project presence/absence matrix (CSV/TSV)")
    parser.add_argument(
        "--project-mapping",
        default=DEFAULT_PROJECT_MAPPING_PATH,
        help="Path to project mapping CSV/TSV (genotyping_source + project_code)",
    )
    parser.add_argument(
        "--owner-contacts",
        default=DEFAULT_OWNER_CONTACTS_PATH,
        help="Path to owner contacts CSV/TSV keyed by owner_name",
    )
    parser.add_argument(
        "--allow-custom-metadata-paths",
        action="store_true",
        help=(
            "Allow non-canonical metadata paths. By default, imports require "
            "data/presence_absence/HapSearch_mapping.csv and HapSearch_owner_contacts.csv."
        ),
    )
    parser.add_argument(
        "--presence-artifact-dir",
        help="Directory for compressed presence artifacts (default: data/presence_artifacts)",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")

    args = parser.parse_args()

    importer = ProjectPresenceImporter()
    verbose = not args.quiet
    canonical_mapping_path = os.path.realpath(DEFAULT_PROJECT_MAPPING_PATH)
    canonical_owner_contacts_path = os.path.realpath(DEFAULT_OWNER_CONTACTS_PATH)
    resolved_mapping_path = os.path.realpath(args.project_mapping)
    resolved_owner_contacts_path = os.path.realpath(args.owner_contacts)

    if not args.allow_custom_metadata_paths:
        noncanonical_paths = []
        if resolved_mapping_path != canonical_mapping_path:
            noncanonical_paths.append(
                f"--project-mapping={args.project_mapping} (expected {DEFAULT_PROJECT_MAPPING_PATH})"
            )
        if resolved_owner_contacts_path != canonical_owner_contacts_path:
            noncanonical_paths.append(
                f"--owner-contacts={args.owner_contacts} (expected {DEFAULT_OWNER_CONTACTS_PATH})"
            )
        if noncanonical_paths:
            raise ValueError(
                "Canonical metadata files are required by default. "
                "Use --allow-custom-metadata-paths to override. "
                + "; ".join(noncanonical_paths)
            )

    importer.import_project_presence(
        args.csv_file,
        args.project_mapping,
        args.owner_contacts,
        verbose=verbose,
        artifact_dir=args.presence_artifact_dir,
    )


if __name__ == "__main__":
    main()
