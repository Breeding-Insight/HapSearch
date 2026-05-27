#!/usr/bin/env python3
"""Auto-detect variants from microhaplotype sequences

Analyzes all alleles at each marker to identify:
- SNPs (single nucleotide polymorphisms)
- Indels (insertions/deletions)
- Target SNPs (can be manually specified)

The script compares all sequences and identifies positions where they differ.
"""

import sys
import os
from collections import Counter
from typing import List, Dict, Tuple

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager


class VariantDetector:
    """Detect variants from aligned sequences"""

    def __init__(self):
        self.db = DatabaseManager()

    def get_markers_with_sequences(self, species_id: int = None) -> List[Dict]:
        """Get all markers and their associated sequences"""
        query = """
            SELECT
                mk.id as marker_id,
                mk.marker_id as marker_name,
                mk.position_start,
                m.id as haplotype_id,
                m.haplotype_sequence
            FROM markers mk
            JOIN microhaplotypes m ON mk.id = m.marker_id
        """

        params = []
        if species_id:
            query += """
                JOIN chromosomes c ON mk.chromosome_id = c.id
                WHERE c.species_id = ?
            """
            params.append(species_id)

        query += " ORDER BY mk.id"

        return self.db.execute_query(query, tuple(params))

    def detect_variants_for_marker(self, sequences: List[str], marker_position: int) -> List[Dict]:
        """
        Detect variants by comparing sequences at a marker

        Returns list of variants with position, type, ref, alt, frequency
        """
        if not sequences or len(sequences) < 2:
            return []

        # Find the longest sequence to use as reference
        max_len = max(len(seq) for seq in sequences)

        # Pad sequences to same length for comparison
        padded_seqs = []
        for seq in sequences:
            padded = seq + '-' * (max_len - len(seq))
            padded_seqs.append(padded)

        variants = []

        # Analyze each position
        for pos_idx in range(max_len):
            bases_at_pos = [seq[pos_idx].upper() for seq in padded_seqs if pos_idx < len(seq)]

            # Skip if all sequences are the same at this position
            unique_bases = set(bases_at_pos)
            if len(unique_bases) <= 1:
                continue

            # Count occurrences
            base_counts = Counter(bases_at_pos)
            total_seqs = len(bases_at_pos)

            # Determine reference allele (most common)
            ref_allele = base_counts.most_common(1)[0][0]

            # Find alternate alleles
            for alt_allele, count in base_counts.items():
                if alt_allele == ref_allele:
                    continue

                frequency = count / total_seqs

                # Classify variant type
                if ref_allele == '-' or alt_allele == '-':
                    # Indel (insertion or deletion)
                    variant_type = 'Indel'
                    if ref_allele == '-':
                        ref_allele = ''  # Insertion
                    if alt_allele == '-':
                        alt_allele = ''  # Deletion
                else:
                    # SNP (single nucleotide polymorphism)
                    variant_type = 'SNP'

                # Calculate genomic position
                genomic_position = marker_position + pos_idx

                variants.append({
                    'position': genomic_position,
                    'variant_type': variant_type,
                    'reference_allele': ref_allele if ref_allele else '-',
                    'alternate_allele': alt_allele if alt_allele else '-',
                    'frequency': frequency
                })

        return variants

    def detect_all_variants(self, species_id: int = None, verbose: bool = True) -> Dict[str, int]:
        """
        Detect variants for all markers in the database

        Returns statistics about detected variants
        """
        if verbose:
            print("Detecting variants from sequences...")
            if species_id:
                print(f"Filtering by species ID: {species_id}")

        # Get all markers and their sequences
        data = self.get_markers_with_sequences(species_id)

        if not data:
            print("No markers found in database!")
            return {'markers': 0, 'variants': 0}

        # Group sequences by marker
        markers_dict = {}
        for row in data:
            marker_id = row['marker_id']
            if marker_id not in markers_dict:
                markers_dict[marker_id] = {
                    'marker_name': row['marker_name'],
                    'position_start': row['position_start'],
                    'sequences': []
                }
            markers_dict[marker_id]['sequences'].append(row['haplotype_sequence'])

        if verbose:
            print(f"Found {len(markers_dict)} markers to analyze")

        # Detect variants for each marker
        stats = {
            'markers_analyzed': 0,
            'markers_with_variants': 0,
            'total_variants': 0,
            'snps': 0,
            'indels': 0
        }

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for marker_id, marker_data in markers_dict.items():
                sequences = marker_data['sequences']
                marker_position = marker_data['position_start']

                # Detect variants
                variants = self.detect_variants_for_marker(sequences, marker_position)

                stats['markers_analyzed'] += 1

                if variants:
                    stats['markers_with_variants'] += 1

                    # Insert variants into database
                    for variant in variants:
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
                            marker_id,
                            variant['position'],
                            variant['variant_type'],
                            variant['reference_allele'],
                            variant['alternate_allele'],
                            marker_id,
                            variant['position'],
                            variant['variant_type'],
                            variant['reference_allele'],
                            variant['alternate_allele'],
                            variant['frequency']
                        ))

                        stats['total_variants'] += 1
                        if variant['variant_type'] == 'SNP':
                            stats['snps'] += 1
                        else:
                            stats['indels'] += 1

                    # Commit every 100 markers
                    if stats['markers_analyzed'] % 100 == 0:
                        conn.commit()
                        if verbose:
                            print(f"  Processed {stats['markers_analyzed']} markers, "
                                  f"found {stats['total_variants']} variants so far...")

            # Final commit
            conn.commit()

        if verbose:
            print(f"\n✓ Variant detection complete!")
            print(f"  Markers analyzed: {stats['markers_analyzed']}")
            print(f"  Markers with variants: {stats['markers_with_variants']}")
            print(f"  Total variants detected: {stats['total_variants']}")
            print(f"    - SNPs: {stats['snps']}")
            print(f"    - Indels: {stats['indels']}")

        return stats


def main():
    """Command-line interface"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Auto-detect variants from microhaplotype sequences',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  # Detect variants for all species
  python detect_variants.py

  # Detect variants for specific species
  python detect_variants.py --species-id 1

  # Quiet mode
  python detect_variants.py --quiet

This script analyzes all sequences at each marker and identifies:
- SNPs: Positions where single nucleotides differ
- Indels: Positions with insertions or deletions

Variants are automatically inserted into the database and will appear
in the MSA viewer with colored annotations.
        """
    )

    parser.add_argument('--species-id', type=int, help='Only detect variants for specific species')
    parser.add_argument('--quiet', action='store_true', help='Suppress verbose output')

    args = parser.parse_args()

    try:
        detector = VariantDetector()
        stats = detector.detect_all_variants(
            species_id=args.species_id,
            verbose=not args.quiet
        )

        print(f"\n✓ Successfully detected and stored {stats['total_variants']} variants!")
        sys.exit(0)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
