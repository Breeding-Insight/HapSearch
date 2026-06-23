#!/usr/bin/env python3
"""Import allele-sample presence/absence data into HaploSearch database

Expected CSV format:
- First column: AlleleID (haplotype_name, e.g., chr1.1_00019|RefMatch_0001)
- Remaining columns: Sample names (e.g., "Legacy FD4", "CADL-5-3")
- Cell values: 1 (present) or 0 (absent)

Example:
AlleleID,Legacy FD4,CADL-5-3,GAMS 1405-F
chr1.1_00019|RefMatch_0001,1,0,1
chr1.1_00030|Alt_0002,0,1,1
"""

import sys
import os
import time
import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager, get_or_create_species
from database.presence_artifacts import (
    counts_by_microhaplotype,
    ensure_presence_artifact_schema,
    record_presence_artifact,
    upsert_presence_summary,
    write_presence_bitmap_artifact,
    write_presence_lookup_artifact,
)
from database.queries import get_all_species
from scripts.presence_metadata import (
    get_or_upsert_project,
    link_project_contacts,
    load_owner_contacts,
    load_project_mapping,
    normalize_project_code,
    pick_mapping_for_source,
    parse_sample_filename_context,
    resolve_project_record,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROJECT_MAPPING_PATH = os.path.join(
    _REPO_ROOT, "data", "presence_absence", "HapSearch_mapping.csv"
)
DEFAULT_OWNER_CONTACTS_PATH = os.path.join(
    _REPO_ROOT, "data", "presence_absence", "HapSearch_owner_contacts.csv"
)


class PresenceImporter:
    """Import allele-sample presence/absence data from CSV files"""

    def __init__(self):
        self.db = DatabaseManager()

    def get_existing_species(self) -> List[Dict[str, Any]]:
        """Get all existing species"""
        return get_all_species(self.db)

    def resolve_species_id_by_name(self, species_name: str) -> int:
        """Resolve species ID by scientific name or common name (case-insensitive)."""
        normalized = (species_name or "").strip()
        if not normalized:
            raise ValueError("Species name cannot be empty")

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, common_name
                FROM species
                WHERE LOWER(name) = LOWER(?)
                   OR LOWER(COALESCE(common_name, '')) = LOWER(?)
                ORDER BY id
                """,
                (normalized, normalized),
            )
            rows = cursor.fetchall()

        if not rows:
            raise ValueError(
                f"No species found matching '{species_name}'. "
                "Use --species-id or create the species first."
            )
        if len(rows) > 1:
            matches = ", ".join([f"{int(r[0])}:{str(r[1])}" for r in rows[:10]])
            raise ValueError(
                f"Multiple species matched '{species_name}'. "
                f"Use --species-id to disambiguate. Matches: {matches}"
            )
        return int(rows[0][0])

    def get_existing_projects(self) -> List[Dict[str, Any]]:
        """Get all existing projects"""
        query = """
            SELECT id, project_code, project_name
            FROM projects
            ORDER BY project_code
        """
        return self.db.execute_query(query)

    def resolve_project_from_filename(
        self,
        csv_path: str,
        mapping_by_source: Dict[str, List[Dict[str, str]]],
        contacts_by_owner: Dict[str, Dict[str, str]],
        verbose: bool = True,
    ) -> int:
        """Resolve canonical project_id from sample-level filename via mapping file."""
        file_ctx = parse_sample_filename_context(csv_path)
        source_key = file_ctx.get("genotyping_source") or ""
        tokens = file_ctx.get("genotyping_tokens") or []

        if not source_key:
            raise ValueError(
                f"No DAI/DAl token found in sample-level file name: {os.path.basename(csv_path)}"
            )

        # Validation files with multiple DAI tags should remain grouped.
        if file_ctx.get("is_validation") and len(tokens) > 1 and verbose:
            print(f"Detected validation grouped source: {source_key}", flush=True)

        mapping_row = pick_mapping_for_source(
            source_key,
            mapping_by_source,
            context_text=os.path.basename(csv_path),
        )
        if not mapping_row:
            raise ValueError(
                f"No project mapping found for genotyping_source '{source_key}'. "
                "Add a row to the project-mapping file."
            )
        canonical_project_code = normalize_project_code(mapping_row["project_code"])

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            lookup_codes = [canonical_project_code]
            if mapping_row.get("project_code"):
                raw_mapping_code = str(mapping_row["project_code"]).strip()
                if raw_mapping_code and raw_mapping_code not in lookup_codes:
                    lookup_codes.append(raw_mapping_code)
            placeholders = ",".join(["?"] * len(lookup_codes))
            cursor.execute(
                f"""
                SELECT id, project_code FROM projects
                WHERE project_code IN ({placeholders})
                ORDER BY CASE WHEN project_code = ? THEN 0 ELSE 1 END, id
                """,
                tuple(lookup_codes + [canonical_project_code]),
            )
            rows = cursor.fetchall()

            if len(rows) == 1:
                if verbose:
                    print(
                        f"Resolved project from filename source '{source_key}' -> '{rows[0][1]}'",
                        flush=True,
                    )
                return int(rows[0][0])

            if len(rows) > 1:
                print(
                    f"Warning: Multiple projects matched code '{canonical_project_code}', using '{rows[0][1]}'",
                    flush=True,
                )
                return int(rows[0][0])

            owner_names = mapping_row.get("owner_names") or []
            if not owner_names:
                fallback_owner = mapping_row.get("owner_name") or ""
                owner_names = [fallback_owner] if fallback_owner else []

            for on in owner_names:
                if on and on.casefold() not in contacts_by_owner:
                    if verbose:
                        print(
                            f"Warning: missing owner contact row for '{on}'; blank contact fields will be used.",
                            flush=True,
                        )

            parsed = {
                "internal_project_id": None,
                "owner": owner_names[0] if owner_names else "",
                "informal_name": mapping_row.get("project_name") or source_key,
                "genotyping_source": source_key,
                "raw_header": canonical_project_code,
            }
            resolved = resolve_project_record(
                parsed,
                mapping_row,
                contacts_by_owner,
                forced_project_code=canonical_project_code,
            )
            project_id, _, _ = get_or_upsert_project(cursor, resolved)

            if owner_names:
                link_project_contacts(
                    cursor, project_id, owner_names, contacts_by_owner
                )

            return int(project_id)

    def create_species_interactive(self) -> Optional[int]:
        """Interactively create a new species"""
        print("\nCreate new species:")
        name = input("  Scientific name (required): ").strip()
        if not name:
            print("  Error: Scientific name is required")
            return None
        
        common_name = input("  Common name (optional): ").strip() or None
        description = input("  Description (optional): ").strip() or None
        
        try:
            species_id = get_or_create_species(self.db, name, common_name, description)
            print(f"  Created species: {name} (ID: {species_id})")
            return species_id
        except Exception as e:
            print(f"  Error creating species: {e}")
            return None

    def create_project_interactive(self) -> Optional[int]:
        """Interactively create a new project"""
        print("\nCreate new project:")
        project_code = input("  Project code (required): ").strip()
        if not project_code:
            print("  Error: Project code is required")
            return None
        
        project_name = input("  Project name (required): ").strip()
        if not project_name:
            print("  Error: Project name is required")
            return None
        
        pi_name = input("  PI name (optional): ").strip() or None
        pi_email = input("  PI email (optional): ").strip() or None
        pi_institution = input("  PI institution (optional): ").strip() or None
        pi_department = input("  PI department (optional): ").strip() or None
        description = input("  Description (optional): ").strip() or None
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO projects
                    (project_code, project_name, pi_name, pi_email,
                     pi_institution, pi_department, description)
                    OUTPUT INSERTED.id
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project_code, project_name, pi_name, pi_email,
                     pi_institution, pi_department, description)
                )
                row = cursor.fetchone()
                if not row or row[0] is None:
                    raise RuntimeError("Failed to retrieve inserted project ID")
                project_id = int(row[0])
                print(f"  Created project: {project_code} - {project_name} (ID: {project_id})")
                return project_id
        except Exception as e:
            print(f"  Error creating project: {e}")
            return None

    def select_species_interactive(self) -> Optional[int]:
        """Interactively select or create a species"""
        species_list = self.get_existing_species()
        
        if not species_list:
            print("\nNo species found in database.")
            response = input("Create a new species? (yes/no): ").strip().lower()
            if response in ['yes', 'y']:
                return self.create_species_interactive()
            return None
        
        print("\nExisting species:")
        for i, species in enumerate(species_list, 1):
            common = f" ({species['common_name']})" if species.get('common_name') else ""
            print(f"  {i}. {species['name']}{common}")
        print(f"  {len(species_list) + 1}. Create new species")
        
        while True:
            try:
                choice = input(f"\nSelect species (1-{len(species_list) + 1}): ").strip()
                choice_num = int(choice)
                
                if 1 <= choice_num <= len(species_list):
                    selected = species_list[choice_num - 1]
                    print(f"Selected: {selected['name']}")
                    return selected['id']
                elif choice_num == len(species_list) + 1:
                    return self.create_species_interactive()
                else:
                    print(f"Invalid choice. Please enter 1-{len(species_list) + 1}")
            except ValueError:
                print("Invalid input. Please enter a number.")
            except KeyboardInterrupt:
                print("\nCancelled.")
                return None

    def get_or_create_sample(self, sample_code: str, project_id: int, 
                            species_id: int, cursor) -> tuple:
        """Get sample ID or create if doesn't exist
        
        Returns:
            tuple: (sample_id, was_created) where was_created is True if sample was just created
        """
        # Check if exists
        cursor.execute(
            "SELECT id FROM samples WHERE sample_code = ?",
            (sample_code,)
        )
        result = cursor.fetchone()
        if result:
            return (result[0], False)
        
        # Create new sample
        cursor.execute(
            """
            INSERT INTO samples
            (sample_code, project_id, species_id)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?)
            """,
            (sample_code, project_id, species_id)
        )
        row = cursor.fetchone()
        if not row or row[0] is None:
            raise RuntimeError(f"Failed to retrieve inserted sample ID for '{sample_code}'")
        return (int(row[0]), True)

    def validate_haplotype_exists(self, haplotype_name: str) -> bool:
        """Check if haplotype_name exists in microhaplotypes table"""
        query = "SELECT COUNT(*) as count FROM microhaplotypes WHERE haplotype_name = ?"
        result = self.db.execute_query(query, (haplotype_name,))
        return result[0]['count'] > 0 if result else False

    def import_presence_data(
        self,
        csv_path: str,
        species_id: int,
        project_id: int,
        verbose: bool = True,
        artifact_dir: Optional[str] = None,
    ) -> Dict[str, int]:
        """Import presence/absence data from CSV file"""
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        if verbose:
            print(f"\nImporting presence data from: {csv_path}", flush=True)
        start_time = time.time()

        # Read CSV
        df = pd.read_csv(csv_path)

        # First column should be AlleleID
        if len(df.columns) < 2:
            raise ValueError("CSV must have at least 2 columns (AlleleID + at least one sample)")

        allele_id_col = df.columns[0]
        sample_columns = df.columns[1:].tolist()

        if verbose:
            print(f"Found {len(df)} alleles and {len(sample_columns)} samples", flush=True)
            print(f"Sample columns: {', '.join(sample_columns[:5])}{'...' if len(sample_columns) > 5 else ''}", flush=True)

        # Validate species and project exist
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM species WHERE id = ?", (species_id,))
            if not cursor.fetchone():
                raise ValueError(f"Species ID {species_id} not found")

            cursor.execute("SELECT id FROM projects WHERE id = ?", (project_id,))
            if not cursor.fetchone():
                raise ValueError(f"Project ID {project_id} not found")

        imported_count = 0
        deleted_count = 0
        skipped_alleles = 0
        skipped_samples = 0
        created_samples = 0
        errors = 0

        def chunked(items, size):
            for i in range(0, len(items), size):
                yield items[i:i + size]

        in_clause_chunk = 400

        # Normalize sample headers once and preserve order.
        sample_columns = [str(col).strip() for col in sample_columns if str(col).strip()]

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            if verbose:
                print("Phase 1/3: Resolving AlleleID -> microhaplotype_id mappings...", flush=True)
            allele_ids_in_file = []
            seen_alleles = set()
            for raw in df[allele_id_col].tolist():
                aid = str(raw).strip()
                if aid and aid not in seen_alleles:
                    allele_ids_in_file.append(aid)
                    seen_alleles.add(aid)

            haplotype_id_map = {}
            for allele_chunk in chunked(allele_ids_in_file, in_clause_chunk):
                placeholders = ",".join(["?"] * len(allele_chunk))
                cursor.execute(
                    f"SELECT id, haplotype_name FROM microhaplotypes WHERE haplotype_name IN ({placeholders})",
                    tuple(allele_chunk)
                )
                for row in cursor.fetchall():
                    haplotype_id_map[str(row[1])] = int(row[0])
            if verbose:
                print(
                    f"  Mapped {len(haplotype_id_map):,}/{len(allele_ids_in_file):,} allele IDs",
                    flush=True
                )

            if verbose:
                print("Phase 2/3: Resolving/creating sample IDs...", flush=True)
            sample_id_map = {}
            if sample_columns:
                for sample_chunk in chunked(sample_columns, in_clause_chunk):
                    placeholders = ",".join(["?"] * len(sample_chunk))
                    cursor.execute(
                        f"SELECT id, sample_code FROM samples WHERE sample_code IN ({placeholders})",
                        tuple(sample_chunk)
                    )
                    for row in cursor.fetchall():
                        sample_id_map[str(row[1])] = int(row[0])

            missing_samples = [s for s in sample_columns if s not in sample_id_map]
            for sample_code in missing_samples:
                sample_id, was_created = self.get_or_create_sample(
                    sample_code, project_id, species_id, cursor
                )
                if sample_id:
                    sample_id_map[sample_code] = int(sample_id)
                    if was_created:
                        created_samples += 1
                else:
                    skipped_samples += 1
            if verbose:
                print(
                    f"  Ready {len(sample_id_map):,} samples ({created_samples:,} created)",
                    flush=True
                )

            sample_ids = sorted(set(sample_id_map[s] for s in sample_columns if s in sample_id_map))
            mh_ids_in_file = sorted(haplotype_id_map.values())

            # Build presence=1 pairs using vectorized numpy operations.
            if verbose:
                print("Phase 3/3: Building presence pairs and bulk loading...", flush=True)

            numeric_presence = df[sample_columns].apply(pd.to_numeric, errors='coerce')
            presence_matrix = numeric_presence.fillna(0).eq(1).to_numpy(dtype=bool)
            sample_id_array = np.array([sample_id_map.get(s, -1) for s in sample_columns], dtype=np.int64)
            valid_sample_mask = sample_id_array > 0
            allele_series = df[allele_id_col].astype(str).str.strip()

            pairs = []
            for idx, allele_id in enumerate(allele_series):
                if not allele_id:
                    continue
                microhaplotype_id = haplotype_id_map.get(allele_id)
                if not microhaplotype_id:
                    skipped_alleles += 1
                    if verbose and skipped_alleles <= 10:
                        print(f"Warning: AlleleID '{allele_id}' not found in microhaplotypes, skipping", flush=True)
                    continue
                present_indices = np.flatnonzero(presence_matrix[idx] & valid_sample_mask)
                for pos in present_indices.tolist():
                    pairs.append((microhaplotype_id, int(sample_id_array[pos])))

            if verbose:
                print(f"  Built {len(pairs):,} presence pairs", flush=True)

            if verbose:
                print("  Writing compressed sample presence artifacts...", flush=True)
            ensure_presence_artifact_schema(cursor)
            metadata = write_presence_bitmap_artifact(
                pairs,
                mh_ids_in_file,
                sample_ids,
                entity_type="sample",
                species_id=species_id,
                project_id=project_id,
                source_path=csv_path,
                output_dir=artifact_dir,
            )
            artifact_id = record_presence_artifact(cursor, metadata)
            lookup_metadata = write_presence_lookup_artifact(
                pairs,
                mh_ids_in_file,
                sample_ids,
                entity_type="sample_lookup",
                species_id=species_id,
                project_id=project_id,
                source_path=csv_path,
                output_dir=artifact_dir,
            )
            record_presence_artifact(cursor, lookup_metadata)
            if artifact_id:
                upsert_presence_summary(
                    cursor,
                    artifact_id=artifact_id,
                    species_id=species_id,
                    entity_type="sample",
                    total_count=len(sample_ids),
                    counts_by_microhaplotype=counts_by_microhaplotype(
                        pairs,
                        mh_ids_in_file,
                    ),
                )
            conn.commit()
            imported_count = len(pairs)
            if verbose:
                size_mb = (metadata.get("artifact_size_bytes") or 0) / 1024 / 1024
                lookup_size_mb = (lookup_metadata.get("artifact_size_bytes") or 0) / 1024 / 1024
                print(
                    f"  Allele->sample artifact: {metadata['artifact_path']} ({size_mb:.2f} MB)",
                    flush=True,
                )
                print(
                    f"  Sample->allele artifact: {lookup_metadata['artifact_path']} ({lookup_size_mb:.2f} MB)",
                    flush=True,
                )

        if verbose:
            total_elapsed = time.time() - start_time
            print(f"\nImport complete!", flush=True)
            print(f"  Imported: {imported_count} new presence records", flush=True)
            print(f"  Deleted: {deleted_count} stale presence records", flush=True)
            print(f"  Created: {created_samples} new samples", flush=True)
            print(f"  Skipped alleles (not found): {skipped_alleles}", flush=True)
            print(f"  Skipped samples: {skipped_samples}", flush=True)
            print(f"  Total time: {total_elapsed:.1f}s", flush=True)
            if errors > 0:
                print(f"  Errors: {errors}", flush=True)

        return {
            'imported': imported_count,
            'deleted': deleted_count,
            'created_samples': created_samples,
            'skipped_alleles': skipped_alleles,
            'skipped_samples': skipped_samples,
            'errors': errors
        }


def main():
    """Command-line interface"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Import allele-sample presence/absence data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CSV Format:
  - First column: AlleleID (haplotype_name)
  - Remaining columns: Sample names
  - Cell values: 1 (present) or 0 (absent)

Example:
  AlleleID,Sample1,Sample2,Sample3
  chr1.1_00019|RefMatch_0001,1,0,1
  chr1.1_00030|Alt_0002,0,1,1
        """
    )

    parser.add_argument('input_path', help='Path to presence/absence CSV file or directory of CSV files')
    parser.add_argument(
        '--project-mapping',
        default=DEFAULT_PROJECT_MAPPING_PATH,
        help='Path to project mapping CSV/TSV (genotyping_source + project_code)'
    )
    parser.add_argument(
        '--owner-contacts',
        default=DEFAULT_OWNER_CONTACTS_PATH,
        help='Path to owner contacts CSV/TSV keyed by owner_name'
    )
    parser.add_argument(
        '--allow-custom-metadata-paths',
        action='store_true',
        help=(
            'Allow non-canonical metadata paths. By default, imports require '
            'data/presence_absence/HapSearch_mapping.csv and HapSearch_owner_contacts.csv.'
        )
    )
    parser.add_argument('--species-id', type=int, help='Species ID (skip interactive prompt)')
    parser.add_argument(
        '--species-name',
        help='Species scientific/common name (skip interactive prompt)'
    )
    parser.add_argument('--project-id', type=int, help='Deprecated: project now resolves from each filename')
    parser.add_argument(
        '--presence-artifact-dir',
        help='Directory for compressed presence artifacts (default: data/presence_artifacts)'
    )
    parser.add_argument('--quiet', action='store_true', help='Suppress verbose output')

    args = parser.parse_args()

    try:
        importer = PresenceImporter()
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

        mapping_result = load_project_mapping(args.project_mapping)
        contacts_result = load_owner_contacts(args.owner_contacts)
        mapping_by_source = mapping_result.by_genotyping_source
        contacts_by_owner = contacts_result.by_owner_name

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

        # Resolve input files (single file or directory)
        if os.path.isdir(args.input_path):
            input_files = sorted(
                [
                    os.path.join(args.input_path, f)
                    for f in os.listdir(args.input_path)
                    if f.lower().endswith('.csv')
                ]
            )
            if not input_files:
                raise ValueError(f"No CSV files found in directory: {args.input_path}")
        else:
            if not os.path.exists(args.input_path):
                raise FileNotFoundError(f"Input file not found: {args.input_path}")
            input_files = [args.input_path]

        # Get species
        if args.species_id and args.species_name:
            raise ValueError("Use either --species-id or --species-name, not both.")

        if args.species_id:
            species_id = args.species_id
        elif args.species_name:
            species_id = importer.resolve_species_id_by_name(args.species_name)
            if verbose:
                print(
                    f"Resolved species '{args.species_name}' -> ID {species_id}",
                    flush=True,
                )
        else:
            species_id = importer.select_species_interactive()
            if not species_id:
                print("Error: Species selection required", file=sys.stderr)
                sys.exit(1)

        if args.project_id and verbose:
            print(
                "Warning: --project-id is deprecated and ignored. "
                "project_id is resolved from each input filename.",
                flush=True,
            )

        aggregate = {
            'imported': 0,
            'deleted': 0,
            'created_samples': 0,
            'skipped_alleles': 0,
            'skipped_samples': 0,
            'errors': 0
        }

        for i, input_file in enumerate(input_files, 1):
            if verbose:
                print(
                    f"\n=== Importing file {i}/{len(input_files)}: {os.path.basename(input_file)} ===",
                    flush=True,
                )
            project_id = importer.resolve_project_from_filename(
                input_file,
                mapping_by_source,
                contacts_by_owner,
                verbose=verbose
            )

            results = importer.import_presence_data(
                input_file,
                species_id,
                project_id,
                verbose,
                artifact_dir=args.presence_artifact_dir,
            )
            for k in aggregate.keys():
                aggregate[k] += int(results.get(k, 0))

        if aggregate['errors'] > 0 and aggregate['errors'] > aggregate['imported']:
            sys.exit(1)

        print("\nAll imports complete!", flush=True)
        print(f"  Files processed: {len(input_files)}", flush=True)
        print(f"  Imported: {aggregate['imported']}", flush=True)
        print(f"  Deleted stale: {aggregate['deleted']}", flush=True)
        print(f"  Created samples: {aggregate['created_samples']}", flush=True)
        print(f"  Skipped alleles: {aggregate['skipped_alleles']}", flush=True)
        print(f"  Skipped samples: {aggregate['skipped_samples']}", flush=True)
        print(f"  Errors: {aggregate['errors']}", flush=True)
        sys.exit(0)

    except KeyboardInterrupt:
        print("\n\nImport cancelled by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if "9002" in str(e) or "transaction log" in str(e).lower():
            print(
                "Hint: SQL Server transaction log is full. "
                "The current importer stores the matrix as artifacts; check metadata/sample/project writes "
                "and confirm the database was initialized with the current schema.",
                file=sys.stderr,
            )
        import traceback
        if verbose:
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
