#!/usr/bin/env python3
"""Import variant information (SNPs, Indels, Target SNPs) into HaploSearch database

Expected CSV format:
marker_id,position,variant_type,reference_allele,alternate_allele,frequency

variant_type should be one of: SNP, Indel, Target_SNP
"""

import sys
import os
import pandas as pd

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager


class VariantImporter:
    """Import variant data from CSV files"""

    def __init__(self):
        self.db = DatabaseManager()

    def import_variants(self, csv_path: str, verbose: bool = True) -> int:
        """Import variants from CSV file"""
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Variants CSV not found: {csv_path}")

        if verbose:
            print(f"Importing variants from: {csv_path}")

        df = pd.read_csv(csv_path)
        required_cols = ['marker_id', 'position', 'variant_type',
                        'reference_allele', 'alternate_allele']

        # Verify required columns
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"CSV must contain columns: {required_cols}")

        # Verify variant types are valid
        valid_types = {'SNP', 'Indel', 'Target_SNP'}
        invalid_types = set(df['variant_type'].unique()) - valid_types
        if invalid_types:
            raise ValueError(f"Invalid variant types found: {invalid_types}. "
                           f"Must be one of: {valid_types}")

        count = 0
        errors = 0

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for _, row in df.iterrows():
                try:
                    # Get marker database ID
                    cursor.execute(
                        "SELECT id FROM markers WHERE marker_id = ?",
                        (row['marker_id'],)
                    )
                    marker_result = cursor.fetchone()
                    if not marker_result:
                        if verbose and errors < 10:  # Only show first 10 errors
                            print(f"Warning: Marker '{row['marker_id']}' not found")
                        errors += 1
                        continue
                    marker_db_id = marker_result[0]

                    # Insert variant
                    cursor.execute("""
                        IF NOT EXISTS (
                            SELECT 1 FROM variants
                            WHERE marker_id = ?
                              AND position = ?
                              AND variant_type = ?
                              AND reference_allele = ?
                              AND alternate_allele = ?
                        )
                        BEGIN
                            INSERT INTO variants
                            (marker_id, position, variant_type, reference_allele,
                             alternate_allele, frequency)
                            VALUES (?, ?, ?, ?, ?, ?)
                        END
                    """, (
                        marker_db_id,
                        int(row['position']),
                        row['variant_type'],
                        row['reference_allele'],
                        row['alternate_allele'],
                        marker_db_id,
                        int(row['position']),
                        row['variant_type'],
                        row['reference_allele'],
                        row['alternate_allele'],
                        float(row.get('frequency', 0.0))
                    ))

                    if cursor.rowcount > 0:
                        count += 1

                except Exception as e:
                    if verbose and errors < 10:
                        print(f"Error importing variant for marker {row['marker_id']}: {e}")
                    errors += 1

        if verbose:
            print(f"Imported {count} variants")
            if errors > 0:
                print(f"Errors/Skipped: {errors}")

        return count


def main():
    """Command-line interface"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Import variant data into HaploSearch',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example CSV format:
marker_id,position,variant_type,reference_allele,alternate_allele,frequency
MH01,10,SNP,A,T,0.35
MH01,25,Indel,ATG,-,0.12
MH01,50,Target_SNP,G,C,0.45
        """
    )

    parser.add_argument('csv_file', help='Path to variants CSV file')
    parser.add_argument('--quiet', action='store_true', help='Suppress verbose output')

    args = parser.parse_args()

    try:
        importer = VariantImporter()
        count = importer.import_variants(args.csv_file, verbose=not args.quiet)

        print(f"\nSuccessfully imported {count} variants")
        sys.exit(0)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
