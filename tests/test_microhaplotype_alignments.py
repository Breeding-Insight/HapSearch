import os
import shutil
import sqlite3
import tempfile
import unittest

from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from alignment.aligner import merge_reference_alignments, reverse_complement_row
from scripts.align_microhaplotypes import align_database


class MergeReferenceAlignmentsTests(unittest.TestCase):
    def test_keeps_each_pairwise_alignment_and_adds_insert_columns(self):
        reference = SeqRecord(Seq("ACGTAC"), id="L|Ref_0001")
        alignment = merge_reference_alignments(reference, [
            ("L|Alt_0002", "ACGTAC", "ACCTAC"),
            ("L|RefMatch_0001", "AC--GTAC", "ACTTGTAC"),  # inserts TT
            ("L|AltMatch_0001", "ACGTAC", "A-GTA-"),
        ])
        rows = {record.id: str(record.seq) for record in alignment}
        self.assertEqual(alignment[0].id, "L|Ref_0001")
        self.assertEqual(rows, {
            "L|Ref_0001": "AC--GTAC",
            "L|Alt_0002": "AC--CTAC",
            "L|RefMatch_0001": "ACTTGTAC",
            "L|AltMatch_0001": "A---GTA-",
        })

    def test_rejects_an_alignment_against_another_reference(self):
        reference = SeqRecord(Seq("ACGT"), id="L|Ref_0001")
        with self.assertRaises(ValueError):
            merge_reference_alignments(reference, [("L|Alt_0002", "ACGA", "ACGT")])

    def test_reverse_complement_row_keeps_gaps(self):
        self.assertEqual(reverse_complement_row("AC-GTN"), "NAC-GT")
        self.assertEqual(reverse_complement_row(reverse_complement_row("AAG--C")), "AAG--C")


@unittest.skipUnless(shutil.which("Rscript"), "Rscript with pwalign is needed")
class AlignDatabaseTests(unittest.TestCase):
    """The stored rows are pwalign's, with BIGr's settings and orientation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "align.db")
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE markers (id INTEGER PRIMARY KEY, marker_id TEXT);
            CREATE TABLE microhaplotypes (id INTEGER PRIMARY KEY, marker_id INTEGER,
                haplotype_name TEXT, haplotype_sequence TEXT);
            CREATE TABLE botloci (marker_id TEXT);
            INSERT INTO markers VALUES (1, 'top_100'), (2, 'bot_200');
            INSERT INTO botloci VALUES ('bot_200');
            INSERT INTO microhaplotypes VALUES
                (1, 1, 'top_100|Ref_0001', 'AAAAAAAAAA'),
                (2, 1, 'top_100|Alt_0002', 'AAAAAAAA'),
                (3, 2, 'bot_200|Ref_0001', 'ACGTTTGGCC'),
                (4, 2, 'bot_200|Alt_0002', 'ACGTTGGCC');
            """
        )
        conn.commit()
        conn.close()

    def test_stores_pwalign_alignments_with_bigr_settings(self):
        self.assertEqual(align_database(self.db_path, cores=1, log=lambda *_: None), 2)
        conn = sqlite3.connect(self.db_path)
        rows = {
            mid: (ref_id, ref_row, seq_row, score)
            for mid, ref_id, ref_row, seq_row, score in conn.execute(
                "SELECT microhaplotype_id, reference_id, aligned_reference, aligned_sequence, score "
                "FROM microhaplotype_alignments")
        }
        conn.close()
        # Biostrings' own tie choice for a homopolymer deletion (not slid to an end).
        self.assertEqual(rows[2][:3], (1, "AAAAAAAAAA", "AAAAAA--AA"))
        self.assertAlmostEqual(rows[2][3], 6.4, places=4)
        # Bottom-strand loci are aligned reverse complemented, as BIGr does.
        self.assertEqual(rows[4][0], 3)
        self.assertEqual(rows[4][1].replace("-", ""), "GGCCAAACGT")
        self.assertEqual(rows[4][2].replace("-", ""), "GGCCAACGT")


if __name__ == "__main__":
    unittest.main()
