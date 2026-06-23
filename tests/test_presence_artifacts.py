import os
import tempfile
import unittest

from database.presence_artifacts import (
    counts_by_microhaplotype,
    read_entity_ids_for_microhaplotype,
    read_microhaplotype_ids_for_entity,
    write_presence_bitmap_artifact,
    write_presence_lookup_artifact,
)


class PresenceArtifactTests(unittest.TestCase):
    def test_bitmap_artifact_round_trips_present_entities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "matrix.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("AlleleID,S1,S2,S3\n")

            metadata = write_presence_bitmap_artifact(
                [(10, 101), (10, 103), (20, 102)],
                [10, 20],
                [101, 102, 103],
                entity_type="sample",
                species_id=1,
                source_path=source_path,
                output_dir=temp_dir,
            )

            self.assertEqual(metadata["presence_count"], 3)
            self.assertTrue(os.path.exists(metadata["artifact_path"]))
            self.assertTrue(os.path.exists(metadata["metadata_path"]))
            self.assertEqual(
                read_entity_ids_for_microhaplotype(metadata["artifact_path"], 10),
                [101, 103],
            )
            self.assertEqual(
                read_entity_ids_for_microhaplotype(metadata["artifact_path"], 20),
                [102],
            )
            self.assertEqual(
                read_entity_ids_for_microhaplotype(metadata["artifact_path"], 999),
                [],
            )

    def test_counts_by_microhaplotype_deduplicates_entities(self):
        self.assertEqual(
            counts_by_microhaplotype(
                [(10, 101), (10, 101), (10, 102), (20, 101)],
                [10, 20, 30],
            ),
            {10: 2, 20: 1, 30: 0},
        )

    def test_lookup_artifact_round_trips_microhaplotypes_for_entity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "matrix.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("AlleleID,S1,S2,S3\n")

            metadata = write_presence_lookup_artifact(
                [(10, 101), (10, 103), (20, 102)],
                [10, 20],
                [101, 102, 103],
                entity_type="sample_lookup",
                species_id=1,
                source_path=source_path,
                output_dir=temp_dir,
            )

            self.assertEqual(metadata["presence_count"], 3)
            self.assertEqual(
                read_microhaplotype_ids_for_entity(metadata["artifact_path"], 101),
                [10],
            )
            self.assertEqual(
                read_microhaplotype_ids_for_entity(metadata["artifact_path"], 102),
                [20],
            )
            self.assertEqual(
                read_microhaplotype_ids_for_entity(metadata["artifact_path"], 103),
                [10],
            )


if __name__ == "__main__":
    unittest.main()
