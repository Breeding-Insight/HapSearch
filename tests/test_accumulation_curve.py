import os
import tempfile
import unittest

from database.presence_artifacts import write_presence_lookup_artifact
from database.queries import (
    get_microhaplotype_accumulation_data,
    get_microhaplotype_project_sharing_data,
)


class FakeAccumulationDb:
    def __init__(self, sample_artifact_path, project_artifact_path):
        self.sample_artifact_path = sample_artifact_path
        self.project_artifact_path = project_artifact_path

    def execute_query(self, query, params=()):
        if "FROM samples s" in query:
            return [
                {
                    "sample_id": 101,
                    "sample_code": "S101",
                    "project_id": 1,
                    "project_name": "Project One",
                    "description": "genotyping_source=DAl21-6679",
                },
                {
                    "sample_id": 102,
                    "sample_code": "S102",
                    "project_id": 2,
                    "project_name": "Project Two",
                    "description": "genotyping_source=DAl22-7011",
                },
            ]
        if "FROM projects p" in query:
            return [
                {
                    "project_id": 1,
                    "project_name": "Validation",
                    "description": "genotyping_source=DAl21-6679",
                },
                {
                    "project_id": 2,
                    "project_name": "Project Two",
                    "description": "genotyping_source=DAl22-7011",
                },
                {
                    "project_id": 3,
                    "project_name": "Project Three",
                    "description": "genotyping_source=DAl23-8561",
                },
            ]
        if "FROM presence_artifacts" in query and "entity_type = 'project_lookup'" in query:
            return [
                {
                    "artifact_path": self.project_artifact_path,
                    "entity_type": "project_lookup",
                },
            ]
        if "FROM presence_artifacts" in query:
            return [
                {
                    "artifact_path": self.sample_artifact_path,
                    "entity_type": "sample_lookup",
                },
                {
                    "artifact_path": self.project_artifact_path,
                    "entity_type": "project_lookup",
                },
            ]
        return []


class AccumulationCurveTests(unittest.TestCase):
    def test_includes_project_only_presence_without_double_counting_sample_projects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "matrix.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("AlleleID,E1,E2,E3\n")

            sample_lookup = write_presence_lookup_artifact(
                [(10, 101), (20, 102)],
                [10, 20, 30],
                [101, 102],
                entity_type="sample_lookup",
                species_id=1,
                source_path=source_path,
                output_dir=temp_dir,
            )
            project_lookup = write_presence_lookup_artifact(
                [(10, 1), (20, 2), (30, 3)],
                [10, 20, 30],
                [1, 2, 3],
                entity_type="project_lookup",
                species_id=1,
                source_path=source_path,
                output_dir=temp_dir,
            )

            db = FakeAccumulationDb(
                sample_lookup["artifact_path"],
                project_lookup["artifact_path"],
            )
            rows = get_microhaplotype_accumulation_data(db, 1)

        self.assertEqual([row["project_id"] for row in rows], [1, 2, 3])
        self.assertEqual(
            [row["cumulative_unique_microhaplotypes"] for row in rows],
            [1, 2, 3],
        )

    def test_project_sharing_data_collapses_projects_into_owner_groups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "matrix.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("AlleleID,E1,E2,E3\n")

            sample_lookup = write_presence_lookup_artifact(
                [],
                [10, 20, 30, 40, 50, 60],
                [],
                entity_type="sample_lookup",
                species_id=1,
                source_path=source_path,
                output_dir=temp_dir,
            )
            project_lookup = write_presence_lookup_artifact(
                [
                    (10, 1), (10, 2), (10, 3),
                    (20, 1), (20, 2),
                    (30, 2), (30, 3),
                    (40, 1),
                    (50, 3), (60, 3),
                ],
                [10, 20, 30, 40, 50, 60],
                [1, 2, 3],
                entity_type="project_lookup",
                species_id=1,
                source_path=source_path,
                output_dir=temp_dir,
            )

            db = FakeAccumulationDb(
                sample_lookup["artifact_path"],
                project_lookup["artifact_path"],
            )
            summary = get_microhaplotype_project_sharing_data(db, 1)

        self.assertEqual(
            [group["label"] for group in summary["owner_groups"]],
            ["Validation", "BI-NPGS", "Breeding (all)"],
        )
        self.assertEqual(
            [
                (
                    row["group_ids"],
                    row["project_count"],
                    row["microhaplotype_count"],
                    row["category"],
                )
                for row in summary["intersections"]
            ],
            [
                (["validation", "bi_npgs", "breeding"], 3, 0, "common"),
                (["validation", "breeding"], 2, 2, "shared"),
                (["validation", "bi_npgs"], 2, 0, "shared"),
                (["bi_npgs", "breeding"], 2, 0, "shared"),
                (["breeding"], 1, 3, "private"),
                (["validation"], 1, 1, "private"),
                (["bi_npgs"], 1, 0, "private"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
