#!/usr/bin/env python3
"""Import FASTA files into HaploSearch database

Expected FASTA format:
>chr#.#_position|AlleleID [optional description]
ATCGATCGATCG...

Examples:
>chr2.1_000313197|RefMatch_0004
ATCGATCGATCGATCGATCGATCG

>chr2.1_000171719|Alt_0002
GCTAGCTAGCTAGCTAGCTA

Where:
  - chr2.1_000313197 = Marker ID (genomic locus)
  - chr2.1 = Chromosome
  - 000313197 = Position
  - RefMatch_0004 = Allele/haplotype variant name
"""

import sys
import os
import re
from typing import Dict, Tuple, Optional

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Bio import SeqIO
from database.db_manager import DatabaseManager, get_or_create_species
from database.queries import get_all_species


class FastaImporter:
    """Import FASTA files with microhaplotype data"""

    def __init__(self):
        self.db = DatabaseManager()

    def get_existing_species(self):
        """Get all existing species"""
        return get_all_species(self.db)

    def create_species_interactive(self):
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

    def select_species_interactive(self):
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

    def parse_fasta_header(self, header: str, description: str) -> Optional[Dict[str, str]]:
        """
        Parse FASTA header to extract marker ID, haplotype ID, and position info

        Expected format: >chr2.1_000313197|RefMatch_0004 [optional description]
        Where:
          - chr2.1_000313197 = Marker ID (locus)
          - chr2 = Chromosome
          - 000313197 = Position
          - RefMatch_0004 = Allele/haplotype variant

        Returns dict with: marker_id, haplotype_id, chromosome, start, end, description
        """
        # Split on | to separate marker from allele
        if '|' in header:
            marker_id, allele_id = header.split('|', 1)
        else:
            # Fallback: if no |, treat whole header as marker_id
            marker_id = header
            allele_id = "allele_1"

        haplotype_id = header  # Full header as haplotype ID

        # Extract chromosome from marker_id
        # Pattern: chr2.1_000313197 or chr2_000313197
        chromosome = None
        position = None

        # Match patterns like: chr2, chr2.1, chr10, etc.
        chrom_match = re.match(r'(chr\d+(?:\.\d+)?)', marker_id, re.IGNORECASE)
        if chrom_match:
            chromosome = chrom_match.group(1)

            # Extract position (numbers after chromosome)
            pos_match = re.search(r'_(\d+)', marker_id)
            if pos_match:
                position = int(pos_match.group(1))

        # Parse additional description from the full description string
        desc_parts = description.split()
        # Remove the header itself from description
        desc_text = ' '.join([p for p in desc_parts[1:] if p != header]) if len(desc_parts) > 1 else ''

        # For start/end, use position if available, otherwise 0
        start = position if position else 0
        end = start  # Since we don't have explicit end, use same as start

        return {
            'marker_id': marker_id,
            'haplotype_id': haplotype_id,
            'chromosome': chromosome,
            'start': start,
            'end': end,
            'description': desc_text
        }

    def import_fasta_file(self, fasta_path: str, species_id: int = None,
                         species_name: str = None, common_name: str = None, 
                         species_description: str = None,
                         verbose: bool = True) -> Dict[str, int]:
        """
        Import FASTA file into database

        Returns dict with counts of imported records
        """
        if not os.path.exists(fasta_path):
            raise FileNotFoundError(f"FASTA file not found: {fasta_path}")

        if verbose:
            print(f"Importing FASTA file: {fasta_path}")

        # Get or create species
        if species_id is None:
            if species_name:
                # Use provided species name
                species_id = get_or_create_species(
                    self.db, species_name, common_name, species_description
                )
                # Defensive fallback for identity retrieval edge cases.
                if not species_id:
                    fallback = self.db.execute_query(
                        "SELECT id FROM species WHERE name = ?",
                        (species_name,)
                    )
                    if fallback:
                        species_id = fallback[0]["id"]
            else:
                raise ValueError("Either species_id or species_name must be provided")
        else:
            # Verify species exists
            query = "SELECT name FROM species WHERE id = ?"
            result = self.db.execute_query(query, (species_id,))
            if not result:
                raise ValueError(f"Species ID {species_id} not found")
            species_name = result[0]['name']

        if verbose:
            print(f"Species: {species_name} (ID: {species_id})")

        # Counters
        stats = {
            'sequences': 0,
            'markers': set(),
            'chromosomes': set(),
            'errors': 0
        }

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if hasattr(cursor, "fast_executemany"):
                cursor.fast_executemany = True

            # Cache for chromosomes and markers to avoid repeated lookups
            chrom_cache = {}
            marker_cache = {}
            pending_microhaplotypes = []
            micro_batch_size = 2000

            # Keep an in-memory set so we avoid per-row existence checks.
            # This dramatically reduces network chatter against remote databases.
            existing_haplotype_names = set()
            cursor.execute("SELECT haplotype_name FROM microhaplotypes")
            for row in cursor.fetchall():
                existing_haplotype_names.add(str(row[0]))

            def flush_microhaplotype_batch():
                if not pending_microhaplotypes:
                    return
                cursor.executemany("""
                    INSERT INTO microhaplotypes
                    (marker_id, haplotype_sequence, haplotype_name)
                    VALUES (?, ?, ?)
                """, pending_microhaplotypes)
                pending_microhaplotypes.clear()

            # Parse FASTA file with batched commits
            batch_size = 500

            for record in SeqIO.parse(fasta_path, "fasta"):
                try:
                    # Parse header
                    header_info = self.parse_fasta_header(record.id, record.description)

                    if not header_info:
                        stats['errors'] += 1
                        continue

                    # Get or create chromosome (with caching, using same cursor)
                    chrom_key = header_info.get('chromosome') or 'Unknown'
                    if chrom_key not in chrom_cache:
                        # Check if exists
                        cursor.execute(
                            "SELECT id FROM chromosomes WHERE species_id = ? AND chromosome_name = ?",
                            (species_id, chrom_key)
                        )
                        result = cursor.fetchone()
                        if result:
                            chrom_id = int(result[0])
                        else:
                            # Create new
                            cursor.execute(
                                """
                                INSERT INTO chromosomes (species_id, chromosome_name)
                                OUTPUT INSERTED.id
                                VALUES (?, ?)
                                """,
                                (species_id, chrom_key)
                            )
                            chrom_id = int(cursor.fetchone()[0])
                        if chrom_id is None:
                            raise ValueError(f"Failed to resolve chromosome_id for '{chrom_key}'")
                        chrom_cache[chrom_key] = chrom_id
                    else:
                        chrom_id = chrom_cache[chrom_key]

                    stats['chromosomes'].add(chrom_key)

                    # Get or create marker (with caching, using same cursor)
                    if header_info['marker_id'] not in marker_cache:
                        # Check if exists
                        cursor.execute(
                            "SELECT id FROM markers WHERE marker_id = ?",
                            (header_info['marker_id'],)
                        )
                        result = cursor.fetchone()
                        if result:
                            marker_db_id = int(result[0])
                        else:
                            # Create new
                            cursor.execute(
                                """
                                INSERT INTO markers (marker_id, chromosome_id, position_start,
                                                   position_end, description)
                                OUTPUT INSERTED.id
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    header_info['marker_id'],
                                    chrom_id,
                                    header_info['start'] or 0,
                                    header_info['end'] or 0,
                                    header_info['description']
                                )
                            )
                            marker_db_id = int(cursor.fetchone()[0])
                        if marker_db_id is None:
                            raise ValueError(
                                f"Failed to resolve marker_id for '{header_info['marker_id']}'"
                            )
                        marker_cache[header_info['marker_id']] = marker_db_id
                    else:
                        marker_db_id = marker_cache[header_info['marker_id']]

                    stats['markers'].add(header_info['marker_id'])

                    # Insert microhaplotype
                    sequence = str(record.seq)
                    haplotype_id = header_info['haplotype_id']
                    if haplotype_id not in existing_haplotype_names:
                        existing_haplotype_names.add(haplotype_id)
                        pending_microhaplotypes.append((marker_db_id, sequence, haplotype_id))
                        if len(pending_microhaplotypes) >= micro_batch_size:
                            flush_microhaplotype_batch()

                    stats['sequences'] += 1

                    # Commit every batch_size records to avoid lock issues
                    if stats['sequences'] % batch_size == 0:
                        flush_microhaplotype_batch()
                        conn.commit()
                        if verbose:
                            print(f"  Processed {stats['sequences']} sequences...")

                except Exception as e:
                    print(f"Error processing record {record.id}: {e}")
                    stats['errors'] += 1
                    continue

            # Final commit
            flush_microhaplotype_batch()
            conn.commit()

        if verbose:
            print(f"\nImport complete!")
            print(f"  Sequences imported: {stats['sequences']}")
            print(f"  Unique markers: {len(stats['markers'])}")
            print(f"  Chromosomes: {len(stats['chromosomes'])}")
            if stats['errors'] > 0:
                print(f"  Errors: {stats['errors']}")

        return stats


def main():
    """Command-line interface for FASTA import"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Import FASTA files into HaploSearch database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  python import_fasta.py data/fasta/human.fasta "Homo sapiens" --common-name "Human"
  python import_fasta.py data/fasta/mosquito.fasta "Anopheles gambiae" --common-name "Mosquito"
        """
    )

    parser.add_argument('fasta_file', help='Path to FASTA file')
    parser.add_argument('species_name', nargs='?', help='Species scientific name (optional - will prompt if not provided)')
    parser.add_argument('--common-name', help='Common name for species')
    parser.add_argument('--description', help='Species description')
    parser.add_argument('--species-id', type=int, help='Species ID (skip interactive prompt)')
    parser.add_argument('--quiet', action='store_true', help='Suppress verbose output')

    args = parser.parse_args()

    try:
        importer = FastaImporter()
        
        # Get species ID
        if args.species_id:
            species_id = args.species_id
        elif args.species_name:
            # Use provided species name
            species_id = None
            species_name = args.species_name
        else:
            # Interactive selection
            species_id = importer.select_species_interactive()
            if not species_id:
                print("Error: Species selection required", file=sys.stderr)
                sys.exit(1)
            species_name = None  # Will be looked up from ID
        
        stats = importer.import_fasta_file(
            args.fasta_file,
            species_id=species_id,
            species_name=species_name,
            common_name=args.common_name,
            species_description=args.description,
            verbose=not args.quiet
        )

        # Update chromosome counts
        from database.db_manager import update_chromosome_counts
        update_chromosome_counts(importer.db)

        print("\nDatabase updated successfully!")
        sys.exit(0)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
