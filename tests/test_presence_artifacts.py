import os
import tempfile
import unittest
from unittest.mock import patch

from database.db_manager import DatabaseManager
import numpy as np

import config
from database.presence_artifacts import (
    _pack_entity_rows,
    clear_presence_cache,
    counts_by_microhaplotype,
    counts_from_matrix,
    entity_presence_matrix,
    entity_ids_for_microhaplotype,
    entity_row,
    load_presence_artifact,
    microhaplotype_column,
    microhaplotype_ids_for_entity,
    upsert_presence_summary,
    write_presence_artifact,
)


class PresenceArtifactTests(unittest.TestCase):
    def setUp(self):
        clear_presence_cache()
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.db = DatabaseManager(
            db_path=os.path.join(self._temp_dir.name, "presence.db"),
            read_only=False,
        )
        self.db.ensure_schema()
        self.source_path = os.path.join(self._temp_dir.name, "matrix.csv")
        with open(self.source_path, "w", encoding="utf-8") as handle:
            handle.write("AlleleID,S1,S2,S3\n")

    def _write(self, pairs, microhaplotype_ids, entity_ids, entity_type="sample"):
        with self.db.get_connection() as conn:
            return write_presence_artifact(
                conn.cursor(),
                pairs,
                microhaplotype_ids,
                entity_ids,
                entity_type=entity_type,
                species_id=1,
                source_path=self.source_path,
            )

    def test_artifact_round_trips_presence_in_both_directions(self):
        metadata = self._write([(10, 101), (10, 103), (20, 102)], [10, 20], [101, 102, 103])

        self.assertEqual(metadata["presence_count"], 3)
        self.assertEqual(metadata["entity_count"], 3)
        artifact = load_presence_artifact(self.db, metadata["id"])

        self.assertEqual(microhaplotype_ids_for_entity(artifact, 101), [10])
        self.assertEqual(microhaplotype_ids_for_entity(artifact, 102), [20])
        self.assertEqual(microhaplotype_ids_for_entity(artifact, 103), [10])
        self.assertEqual(microhaplotype_ids_for_entity(artifact, 999), [])
        self.assertEqual(entity_ids_for_microhaplotype(artifact, 10), [101, 103])
        self.assertEqual(entity_ids_for_microhaplotype(artifact, 20), [102])
        self.assertEqual(entity_ids_for_microhaplotype(artifact, 999), [])

    def test_bit_columns_past_first_byte_round_trip(self):
        microhaplotype_ids = list(range(1000, 1019))
        pairs = [(1009, 5), (1017, 5), (1018, 6), (1000, 6)]
        metadata = self._write(pairs, microhaplotype_ids, [5, 6])
        artifact = load_presence_artifact(self.db, metadata["id"])

        self.assertEqual(microhaplotype_ids_for_entity(artifact, 5), [1009, 1017])
        self.assertEqual(microhaplotype_ids_for_entity(artifact, 6), [1000, 1018])
        self.assertEqual(entity_ids_for_microhaplotype(artifact, 1017), [5])
        self.assertEqual(entity_ids_for_microhaplotype(artifact, 1018), [6])

    def test_loaded_artifacts_are_cached_per_database(self):
        metadata = self._write([(10, 101)], [10], [101])

        first = load_presence_artifact(self.db, metadata["id"])
        second = load_presence_artifact(self.db, metadata["id"])

        self.assertIs(first, second)

    def test_lookups_work_on_unsorted_ids(self):
        metadata = self._write(
            [(30, 103), (10, 101), (20, 102)],
            [30, 10, 20],
            [103, 101, 102],
        )
        artifact = load_presence_artifact(self.db, metadata["id"])

        self.assertEqual(entity_row(artifact, 101), 1)
        self.assertIsNone(entity_row(artifact, 100))
        self.assertIsNone(entity_row(artifact, 999))
        self.assertEqual(microhaplotype_column(artifact, 20), 2)
        self.assertEqual(microhaplotype_ids_for_entity(artifact, 103), [30])
        self.assertEqual(entity_ids_for_microhaplotype(artifact, 10), [101])

    def test_cache_drops_least_recently_used_matrices_past_its_size_limit(self):
        microhaplotype_ids = list(range(1, 8001))
        ids = [
            self._write([(1, 101)], microhaplotype_ids, [101])["id"]
            for _ in range(3)
        ]
        one_matrix_mb = 8000 * 8 / (1024 * 1024)

        with patch.object(config, "PRESENCE_CACHE_MAX_MB", one_matrix_mb * 2.5):
            first = load_presence_artifact(self.db, ids[0])
            load_presence_artifact(self.db, ids[1])
            load_presence_artifact(self.db, ids[0])  # now the most recently used
            load_presence_artifact(self.db, ids[2])  # evicts ids[1]

            self.assertIs(load_presence_artifact(self.db, ids[0]), first)
            second_reloaded = load_presence_artifact(self.db, ids[1])
            self.assertEqual(microhaplotype_ids_for_entity(second_reloaded, 101), [1])

    def test_cache_keeps_a_matrix_larger_than_its_size_limit(self):
        metadata = self._write([(10, 101)], [10], [101])

        with patch.object(config, "PRESENCE_CACHE_MAX_MB", 0):
            first = load_presence_artifact(self.db, metadata["id"])
            self.assertIs(load_presence_artifact(self.db, metadata["id"]), first)

    def test_rejects_legacy_lookup_entity_types(self):
        with self.assertRaises(ValueError):
            self._write([], [10], [101], entity_type="sample_lookup")

    def test_sample_summary_accumulates_across_imports(self):
        artifact_ids = [
            self._write([(10, 101)], [10], [101, 102])["id"],
            self._write([(10, 103)], [10], [103, 104])["id"],
        ]
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO species (id, name) VALUES (1, 'Medicago sativa')")
            cursor.execute("INSERT INTO chromosomes (id, species_id, chromosome_name) VALUES (1, 1, 'chr1')")
            cursor.execute(
                "INSERT INTO markers (id, marker_id, chromosome_id, position_start, position_end) "
                "VALUES (1, 'M1', 1, 1, 10)"
            )
            cursor.execute(
                "INSERT INTO microhaplotypes (id, marker_id, haplotype_sequence, haplotype_name) "
                "VALUES (10, 1, 'ACGT', 'M1|Ref')"
            )
            cursor.execute("INSERT INTO projects (id, project_code, project_name) VALUES (1, 'P1', 'P1')")
            cursor.executemany(
                "INSERT INTO samples (id, sample_code, project_id, species_id) VALUES (?, ?, 1, 1)",
                [(101, "S1"), (102, "S2"), (103, "S3"), (104, "S4")],
            )
            for artifact_id in artifact_ids:
                upsert_presence_summary(
                    cursor,
                    artifact_id=artifact_id,
                    species_id=1,
                    entity_type="sample",
                    total_count=2,
                    counts_by_microhaplotype={10: 1},
                )

        summary = self.db.execute_query(
            "SELECT present_count, total_count, frequency FROM microhaplotype_presence_summary"
        )[0]
        microhaplotype = self.db.execute_query(
            "SELECT sample_count, frequency FROM microhaplotypes WHERE id = 10"
        )[0]
        self.assertEqual(summary["present_count"], 2)
        self.assertEqual(summary["total_count"], 4)
        self.assertAlmostEqual(summary["frequency"], 0.5)
        self.assertEqual(microhaplotype["sample_count"], 2)
        self.assertAlmostEqual(microhaplotype["frequency"], 0.5)

    def test_counts_by_microhaplotype_deduplicates_entities(self):
        self.assertEqual(
            counts_by_microhaplotype(
                [(10, 101), (10, 101), (10, 102), (20, 101)],
                [10, 20, 30],
            ),
            {10: 2, 20: 1, 30: 0},
        )



class EntityPresenceMatrixTests(unittest.TestCase):
    """The NumPy import path must match the original (allele, entity) pairs path."""

    def _pairs(self, file_presence, row_mh_ids, column_entity_ids):
        # The importers' original loop: one pair per present cell in a valid row and column.
        pairs = []
        for row, mh_id in enumerate(row_mh_ids):
            if mh_id <= 0:
                continue
            for col, entity_id in enumerate(column_entity_ids):
                if entity_id > 0 and file_presence[row, col]:
                    pairs.append((mh_id, entity_id))
        return pairs

    def _assert_same(self, file_presence, row_mh_ids, column_entity_ids):
        mh_axis = sorted({m for m in row_mh_ids if m > 0})
        entity_axis = sorted({e for e in column_entity_ids if e > 0})
        pairs = self._pairs(file_presence, row_mh_ids, column_entity_ids)
        matrix = entity_presence_matrix(file_presence, row_mh_ids, column_entity_ids, mh_axis, entity_axis)

        from_pairs = _pack_entity_rows(pairs, mh_axis, entity_axis)
        from_matrix = _pack_entity_rows(None, mh_axis, entity_axis, matrix)
        for expected, actual in zip(from_pairs, from_matrix):
            np.testing.assert_array_equal(expected, actual)
        self.assertEqual(counts_from_matrix(matrix, mh_axis), counts_by_microhaplotype(pairs, mh_axis))

    def test_matches_pairs_on_a_random_matrix(self):
        rng = np.random.default_rng(7)
        file_presence = rng.random((60, 45)) < 0.4
        row_mh_ids = list(range(100, 160))
        column_entity_ids = list(range(500, 545))
        self._assert_same(file_presence, row_mh_ids, column_entity_ids)

    def test_matches_pairs_with_unknown_rows_unmapped_columns_and_duplicates(self):
        rng = np.random.default_rng(11)
        file_presence = rng.random((30, 20)) < 0.5
        # Unknown alleles (-1), an allele listed twice, unmapped samples (-1) and
        # a sample listed twice: duplicates are OR-ed, unknowns dropped.
        row_mh_ids = [-1 if i % 7 == 0 else 100 + i for i in range(30)]
        row_mh_ids[5] = row_mh_ids[4]
        column_entity_ids = [-1 if j % 6 == 0 else 500 + j for j in range(20)]
        column_entity_ids[9] = column_entity_ids[8]
        self._assert_same(file_presence, row_mh_ids, column_entity_ids)

    def test_rows_and_columns_out_of_axis_order(self):
        file_presence = np.array([[1, 0, 1], [0, 1, 1]], dtype=bool)
        self._assert_same(file_presence, [205, 201], [9, 3, 7])


if __name__ == "__main__":
    unittest.main()
