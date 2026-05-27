#!/usr/bin/env python3
"""Import bottom-strand locus IDs from a .botloci file.

Expected format:
one marker/locus ID per non-empty line.
"""

import os
import sys
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager
from database.queries import get_botloci_count, upsert_botloci


def parse_botloci_text(text: str) -> List[str]:
    """Parse .botloci text into de-duplicated marker IDs in file order."""
    marker_ids = []
    seen = set()
    for raw_line in (text or "").splitlines():
        marker_id = raw_line.strip()
        if not marker_id or marker_id in seen:
            continue
        marker_ids.append(marker_id)
        seen.add(marker_id)
    return marker_ids


class BotlociImporter:
    """Import bottom-loci lookup data."""

    def __init__(self):
        self.db = DatabaseManager()

    def import_botloci(self, botloci_path: str, verbose: bool = True) -> int:
        """Import marker IDs from a .botloci file."""
        if not os.path.exists(botloci_path):
            raise FileNotFoundError(f"Botloci file not found: {botloci_path}")

        if verbose:
            print(f"Importing bottom loci from: {botloci_path}")

        with open(botloci_path, "r", encoding="utf-8") as handle:
            marker_ids = parse_botloci_text(handle.read())

        inserted = upsert_botloci(self.db, marker_ids)

        if verbose:
            duplicates = len(marker_ids) - inserted
            total = get_botloci_count(self.db)
            print(f"Parsed {len(marker_ids)} unique bottom loci")
            print(f"Imported {inserted} new bottom loci")
            print(f"Skipped existing: {duplicates}")
            print(f"Total stored bottom loci: {total}")

        return inserted


def main():
    """Command-line interface."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Import .botloci bottom-strand locus IDs into HaploSearch"
    )
    parser.add_argument("botloci_file", help="Path to .botloci file")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")
    args = parser.parse_args()

    try:
        importer = BotlociImporter()
        count = importer.import_botloci(args.botloci_file, verbose=not args.quiet)
        print(f"\nSuccessfully imported {count} new bottom loci")
        sys.exit(0)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
