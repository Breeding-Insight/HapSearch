#!/usr/bin/env python3
"""Import sample and project data into HaploSearch database

Expected CSV formats:

projects.csv:
project_code,project_name,pi_name,pi_email,pi_institution,pi_department,description,start_date

samples.csv:
sample_code,project_code,species,sample_type,collection_date,collection_location,notes

associations.csv:
haplotype_name,sample_code,read_count
"""

import sys
import os
import pandas as pd
from typing import Optional

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager


class SampleImporter:
    """Import sample and project data from CSV files"""

    def __init__(self):
        self.db = DatabaseManager()

    def import_projects(self, csv_path: str, verbose: bool = True) -> int:
        """Import projects from CSV file"""
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Projects CSV not found: {csv_path}")

        if verbose:
            print(f"Importing projects from: {csv_path}")

        df = pd.read_csv(csv_path)
        required_cols = ['project_code', 'project_name']

        # Verify required columns
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"CSV must contain columns: {required_cols}")

        count = 0
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for _, row in df.iterrows():
                try:
                    cursor.execute("""
                        IF NOT EXISTS (SELECT 1 FROM projects WHERE project_code = ?)
                        BEGIN
                            INSERT INTO projects
                            (project_code, project_name, pi_name, pi_email,
                             pi_institution, pi_department, description, start_date)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        END
                    """, (
                        row['project_code'],
                        row['project_code'],
                        row['project_name'],
                        row.get('pi_name'),
                        row.get('pi_email'),
                        row.get('pi_institution'),
                        row.get('pi_department'),
                        row.get('description'),
                        row.get('start_date')
                    ))
                    if cursor.rowcount > 0:
                        count += 1
                except Exception as e:
                    print(f"Error importing project {row['project_code']}: {e}")

        if verbose:
            print(f"Imported {count} projects")

        return count

    def import_samples(self, csv_path: str, verbose: bool = True) -> int:
        """Import samples from CSV file"""
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Samples CSV not found: {csv_path}")

        if verbose:
            print(f"Importing samples from: {csv_path}")

        df = pd.read_csv(csv_path)
        required_cols = ['sample_code', 'project_code', 'species']

        # Verify required columns
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"CSV must contain columns: {required_cols}")

        count = 0
        errors = 0

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for _, row in df.iterrows():
                try:
                    # Get project_id
                    cursor.execute(
                        "SELECT id FROM projects WHERE project_code = ?",
                        (row['project_code'],)
                    )
                    project_result = cursor.fetchone()
                    if not project_result:
                        print(f"Warning: Project '{row['project_code']}' not found for sample '{row['sample_code']}'")
                        errors += 1
                        continue
                    project_id = project_result[0]

                    # Get species_id
                    cursor.execute(
                        "SELECT id FROM species WHERE name = ?",
                        (row['species'],)
                    )
                    species_result = cursor.fetchone()
                    if not species_result:
                        print(f"Warning: Species '{row['species']}' not found for sample '{row['sample_code']}'")
                        errors += 1
                        continue
                    species_id = species_result[0]

                    # Insert sample
                    cursor.execute("""
                        IF NOT EXISTS (SELECT 1 FROM samples WHERE sample_code = ?)
                        BEGIN
                            INSERT INTO samples
                            (sample_code, project_id, species_id, sample_type,
                             collection_date, collection_location)
                            VALUES (?, ?, ?, ?, ?, ?)
                        END
                    """, (
                        row['sample_code'],
                        row['sample_code'],
                        project_id,
                        species_id,
                        row.get('sample_type'),
                        row.get('collection_date'),
                        row.get('collection_location'),
                    ))
                    if cursor.rowcount > 0:
                        count += 1

                except Exception as e:
                    print(f"Error importing sample {row['sample_code']}: {e}")
                    errors += 1

        if verbose:
            print(f"Imported {count} samples")
            if errors > 0:
                print(f"Errors: {errors}")

        return count

    def import_associations(self, csv_path: str, verbose: bool = True) -> int:
        """Import microhaplotype-sample associations from CSV file"""
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Associations CSV not found: {csv_path}")

        if verbose:
            print(f"Importing associations from: {csv_path}")

        df = pd.read_csv(csv_path)
        required_cols = ['haplotype_name', 'sample_code']

        # Verify required columns
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"CSV must contain columns: {required_cols}")

        count = 0
        errors = 0

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for _, row in df.iterrows():
                try:
                    # Get haplotype_id
                    cursor.execute(
                        "SELECT id FROM microhaplotypes WHERE haplotype_name = ?",
                        (row['haplotype_name'],)
                    )
                    haplotype_result = cursor.fetchone()
                    if not haplotype_result:
                        errors += 1
                        continue
                    haplotype_id = haplotype_result[0]

                    # Get sample_id
                    cursor.execute(
                        "SELECT id FROM samples WHERE sample_code = ?",
                        (row['sample_code'],)
                    )
                    sample_result = cursor.fetchone()
                    if not sample_result:
                        errors += 1
                        continue
                    sample_id = sample_result[0]

                    # Insert association
                    cursor.execute("""
                        IF NOT EXISTS (SELECT 1 FROM microhaplotype_samples
                                      WHERE microhaplotype_id = ? AND sample_id = ?)
                        BEGIN
                            INSERT INTO microhaplotype_samples
                            (microhaplotype_id, sample_id, read_count)
                            VALUES (?, ?, ?)
                        END
                    """, (
                        haplotype_id,
                        sample_id,
                        haplotype_id,
                        sample_id,
                        row.get('read_count', 0)
                    ))
                    if cursor.rowcount > 0:
                        count += 1

                except Exception as e:
                    errors += 1

        if verbose:
            print(f"Imported {count} associations")
            if errors > 0:
                print(f"Skipped {errors} associations (missing haplotypes/samples)")

        # Update haplotype frequencies and counts
        from database.db_manager import update_haplotype_frequencies
        update_haplotype_frequencies(self.db)

        return count


def main():
    """Command-line interface"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Import sample and project data',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--projects', help='Path to projects CSV file')
    parser.add_argument('--samples', help='Path to samples CSV file')
    parser.add_argument('--associations', help='Path to associations CSV file')
    parser.add_argument('--quiet', action='store_true', help='Suppress verbose output')

    args = parser.parse_args()

    if not any([args.projects, args.samples, args.associations]):
        parser.error("At least one of --projects, --samples, or --associations is required")

    try:
        importer = SampleImporter()
        verbose = not args.quiet

        if args.projects:
            importer.import_projects(args.projects, verbose)

        if args.samples:
            importer.import_samples(args.samples, verbose)

        if args.associations:
            importer.import_associations(args.associations, verbose)

        print("\nImport complete!")
        sys.exit(0)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
