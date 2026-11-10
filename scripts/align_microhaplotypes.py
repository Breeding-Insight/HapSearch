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
{missing_only}
ORDER BY m.id
"""
MISSING_ONLY = "AND m.id NOT IN (SELECT microhaplotype_id FROM microhaplotype_alignments)"


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


def align_database(db_path: str, cores: int = None, log=print, missing_only: bool = False) -> int:
    """Align microhaplotypes to their Ref_0001 and store the result.

    By default every stored alignment is replaced. With missing_only, only
    microhaplotypes without one are aligned (an incremental build keeps the
    alignments of species it did not rebuild). Returns how many were stored.
    """
    rscript = find_rscript()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(CREATE_TABLE)
        pairs = conn.execute(
            PAIRS_QUERY.format(missing_only=MISSING_ONLY if missing_only else "")
        ).fetchall()
        if not pairs:
            if not missing_only:
                conn.execute("DELETE FROM microhaplotype_alignments")
                conn.commit()
            log("  No microhaplotypes need aligning")
            return 0
        log(f"  Aligning {len(pairs):,} microhaplotypes")
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
            # Pass R's progress lines through as they arrive, so a long run
            # shows how far it has got.
            # stderr goes to a file so a chatty R cannot fill its pipe and stall.
            err_path = os.path.join(tmp, "stderr.txt")
            with open(err_path, "w+", encoding="utf-8") as err:
                with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=err,
                                      text=True) as process:
                    for line in process.stdout:
                        line = line.rstrip()
                        if line:
                            log(f"{line} ({time.time() - start:.0f}s)")
                if process.returncode != 0:
                    err.seek(0)
                    raise AlignmentError("Aligning microhaplotypes in R failed:\n" + err.read().strip())

            with open(out_path, newline="", encoding="utf-8") as handle:
                rows = [
                    (int(row["microhaplotype_id"]), reference_of[int(row["microhaplotype_id"])],
                     row["aligned_reference"], row["aligned_sequence"], float(row["score"]))
                    for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
                ]

        if len(rows) != len(pairs):
            raise AlignmentError(f"R returned {len(rows):,} alignments for {len(pairs):,} microhaplotypes")
        if not missing_only:
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
    parser.add_argument("--missing-only", action="store_true",
                        help="Only align microhaplotypes that have no stored alignment")
    args = parser.parse_args()
    try:
        count = align_database(args.db, args.cores, missing_only=args.missing_only)
    except AlignmentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Stored {count:,} alignments in {args.db}")


if __name__ == "__main__":
    main()
