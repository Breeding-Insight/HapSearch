import os
import tempfile
import unittest

from database.db_manager import DatabaseManager
from database.presence_artifacts import (
    clear_presence_cache,
    counts_by_microhaplotype,
    entity_ids_for_microhaplotype,
    load_presence_artifact,
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


if __name__ == "__main__":
    unittest.main()
