import os
import tempfile
import unittest

from database.db_manager import DatabaseManager
from database.presence_artifacts import clear_presence_cache
from scripts.import_sample_presence import PresenceImporter, normalize_sample_code


class NormalizeSampleCodeTests(unittest.TestCase):
    def test_removes_one_pair_of_surrounding_quotes(self):
        self.assertEqual(normalize_sample_code('"1_1-Parent P53V08"'), "1_1-Parent P53V08")
        self.assertEqual(normalize_sample_code("'6_10-Cross BB14-1-b'"), "6_10-Cross BB14-1-b")
        self.assertEqual(normalize_sample_code('  "S1"  '), "S1")

    def test_leaves_other_names_alone(self):
        self.assertEqual(normalize_sample_code("S1"), "S1")
        self.assertEqual(normalize_sample_code('O"Brien-2'), 'O"Brien-2')
        self.assertEqual(normalize_sample_code('"half-quoted'), '"half-quoted')
        self.assertEqual(normalize_sample_code("'mixed\""), "'mixed\"")
        self.assertEqual(normalize_sample_code('"'), '"')


class SamplePresenceImportTests(unittest.TestCase):
    def setUp(self):
        clear_presence_cache()
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.db = DatabaseManager(
            db_path=os.path.join(self._temp_dir.name, "import.db"),
            read_only=False,
        )
        self.db.ensure_schema()
        with self.db.get_connection() as conn:
            conn.executescript(
                """
                INSERT INTO species (id, name) VALUES (1, 'Medicago sativa');
                INSERT INTO chromosomes (id, species_id, chromosome_name) VALUES (1, 1, 'chr1.1');
                INSERT INTO markers (id, marker_id, chromosome_id, position_start, position_end)
                    VALUES (1, 'chr1.1_000194324', 1, 194324, 194405);
                INSERT INTO microhaplotypes (id, marker_id, haplotype_sequence, haplotype_name)
                    VALUES (1, 1, 'ACGT', 'chr1.1_000194324|Ref_0001');
                INSERT INTO projects (id, project_code, project_name) VALUES (1, 'P05', 'Creeping rootedness');
                """
            )
            conn.commit()

    def test_quoted_sample_headers_are_stored_without_quotes(self):
        # Two names with literal quotes (as in DAl22-7249) and one plain name.
        csv_path = os.path.join(self._temp_dir.name, "hapStatus.csv")
        with open(csv_path, "w", encoding="utf-8") as handle:
            handle.write('AlleleID,"""1_1-Parent P53V08""","""6_10-Cross BB14-1-b""",S3\n')
            handle.write("chr1.1_000194324|Ref_0001,1,0,1\n")

        importer = PresenceImporter()
        importer.db = self.db
        result = importer.import_presence_data(csv_path, species_id=1, project_id=1, verbose=False)

        self.assertEqual(result["created_samples"], 3)
        with self.db.get_connection() as conn:
            codes = sorted(row[0] for row in conn.execute("SELECT sample_code FROM samples"))
        self.assertEqual(codes, ["1_1-Parent P53V08", "6_10-Cross BB14-1-b", "S3"])
        # Presence still follows the (renamed) columns: two samples carry the allele.
        self.assertEqual(result["imported"], 2)


if __name__ == "__main__":
    unittest.main()
