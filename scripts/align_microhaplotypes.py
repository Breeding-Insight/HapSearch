#!/usr/bin/env python3
"""Store BIGr's alignment of every microhaplotype to its locus's Ref_0001.

The alignment itself runs in R (scripts/align_microhaplotypes.R) with
pwalign::pairwiseAlignment and BIGr's settings, so the Multiple Sequence
Alignment tab shows exactly the alignment BIGr/BIGapp use. It needs Rscript
with the Bioconductor packages Biostrings and pwalign (on Debian/Ubuntu:
``apt-get install r-bioc-pwalign``).

The build runs this after the imports. To add alignments to an existing
database:

    python scripts/align_microhaplotypes.py --db data/hapsearch.db
"""

import argparse
import csv
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R_SCRIPT = os.path.join(REPO_ROOT, "scripts", "align_microhaplotypes.R")

# Rows are in BIGr's orientation: bottom-strand loci are reverse complemented.
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS microhaplotype_alignments (
    microhaplotype_id INTEGER PRIMARY KEY REFERENCES microhaplotypes(id),
    reference_id INTEGER NOT NULL REFERENCES microhaplotypes(id),
    aligned_reference TEXT NOT NULL,
    aligned_sequence TEXT NOT NULL,
    score REAL NOT NULL
)
"""

# Each microhaplotype paired with its locus's Ref_0001 (the Ref itself is left out).
PAIRS_QUERY = r"""
SELECT m.id, ref.id, CASE WHEN b.marker_id IS NULL THEN 0 ELSE 1 END,
       ref.haplotype_sequence, m.haplotype_sequence
FROM microhaplotypes m
JOIN markers mk ON mk.id = m.marker_id
JOIN microhaplotypes ref
  ON ref.marker_id = m.marker_id AND ref.haplotype_name LIKE '%|Ref\_0001' ESCAPE '\'
LEFT JOIN botloci b ON b.marker_id = mk.marker_id
WHERE m.id != ref.id
ORDER BY m.id
"""


class AlignmentError(RuntimeError):
    """R or pwalign is missing, or the alignment run failed."""


def find_rscript() -> str:
    rscript = shutil.which("Rscript")
    if not rscript:
        raise AlignmentError(
            "Rscript was not found. Install R with the Bioconductor packages Biostrings and "
            "pwalign (Debian/Ubuntu: apt-get install r-bioc-pwalign)."
        )
    return rscript


def align_database(db_path: str, cores: int = None, log=print) -> int:
    """Replace the database's stored alignments; return how many were stored."""
    rscript = find_rscript()
    conn = sqlite3.connect(db_path)
    try:
        pairs = conn.execute(PAIRS_QUERY).fetchall()
        reference_of = {row[0]: row[1] for row in pairs}
        with tempfile.TemporaryDirectory() as tmp:
            in_path = os.path.join(tmp, "pairs.tsv")
            out_path = os.path.join(tmp, "aligned.tsv")
            with open(in_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
                writer.writerow(["microhaplotype_id", "bottom", "reference", "sequence"])
                for mid, _ref_id, bottom, reference, sequence in pairs:
                    writer.writerow([mid, bottom, reference, sequence])

            command = [rscript, R_SCRIPT, in_path, out_path]
            if cores:
                command.append(str(cores))
            start = time.time()
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                raise AlignmentError(
                    "Aligning microhaplotypes in R failed:\n"
                    + (result.stderr or result.stdout).strip()
                )
            log(f"  {result.stdout.strip()} ({time.time() - start:.0f}s)")

            with open(out_path, newline="", encoding="utf-8") as handle:
                rows = [
                    (int(row["microhaplotype_id"]), reference_of[int(row["microhaplotype_id"])],
                     row["aligned_reference"], row["aligned_sequence"], float(row["score"]))
                    for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
                ]

        if len(rows) != len(pairs):
            raise AlignmentError(f"R returned {len(rows):,} alignments for {len(pairs):,} microhaplotypes")
        conn.execute(CREATE_TABLE)
        conn.execute("DELETE FROM microhaplotype_alignments")
        conn.executemany(
            "INSERT INTO microhaplotype_alignments "
            "(microhaplotype_id, reference_id, aligned_reference, aligned_sequence, score) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, help="SQLite database to update")
    parser.add_argument("--cores", type=int, help="Cores for R to use (default: all)")
    args = parser.parse_args()
    try:
        count = align_database(args.db, args.cores)
    except AlignmentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Stored {count:,} alignments in {args.db}")


if __name__ == "__main__":
    main()
