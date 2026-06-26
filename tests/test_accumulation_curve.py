import os
import tempfile
import unittest

from database.presence_artifacts import write_presence_lookup_artifact
from database.queries import (
    get_microhaplotype_accumulation_data,
    get_microhaplotype_project_sharing_data,
)


class FakeAccumulationDb:
    def __init__(self, sample_artifact_path, project_artifact_path, contact_rows=None):
        self.sample_artifact_path = sample_artifact_path
        self.project_artifact_path = project_artifact_path
        self.contact_rows = contact_rows or []
        self.queries = []

    def execute_query(self, query, params=()):
        self.queries.append(query)
        if "FROM project_contacts pc" in query:
            return self.contact_rows
        if "FROM samples s" in query:
            return [
                {
                    "sample_id": 101,
                    "sample_code": "S101",
                    "project_id": 1,
                    "project_name": "Project One",
                    "pi_institution": "Fallback One",
                    "description": "genotyping_source=DAl21-6679",
                },
                {
                    "sample_id": 102,
                    "sample_code": "S102",
                    "project_id": 2,
                    "project_name": "Project Two",
                    "pi_institution": "Fallback Two",
                    "description": "genotyping_source=DAl22-7011",
                },
            ]
        if "FROM projects p" in query:
            return [
                {
                    "project_id": 1,
                    "project_name": "Validation",
                    "pi_institution": "Fallback One",
                    "description": "genotyping_source=DAl21-6679",
                },
                {
                    "project_id": 2,
                    "project_name": "Project Two",
                    "pi_institution": "Fallback Two",
                    "description": "genotyping_source=DAl22-7011",
                },
                {
                    "project_id": 3,
                    "project_name": "Project Three",
                    "pi_institution": "Fallback Three",
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
            sampled_rows = get_microhaplotype_accumulation_data(
                db,
                1,
                max_result_points=2,
            )

        self.assertEqual([row["project_id"] for row in rows], [1, 2, 3])
        self.assertEqual(
            [row["cumulative_unique_microhaplotypes"] for row in rows],
            [1, 2, 3],
        )
        self.assertEqual([row["sample_index"] for row in sampled_rows], [1, 3])
        self.assertEqual(
            [row["cumulative_unique_microhaplotypes"] for row in sampled_rows],
            [1, 3],
        )
        artifact_queries = [
            query for query in db.queries if "FROM presence_artifacts" in query
        ]
        self.assertTrue(
            any("ROW_NUMBER() OVER" in query and "artifact_rank = 1" in query for query in artifact_queries)
        )

    def test_accumulation_labels_institution_then_location(self):
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
                contact_rows=[
                    {"project_id": 1, "institution": "USDA ARS", "location": "Geneva, NY"},
                    {"project_id": 2, "institution": "USDA ARS", "location": "Corvallis, OR"},
                    {"project_id": 3, "institution": "Cornell", "location": "Ithaca, NY"},
                    {"project_id": 3, "institution": "Cornell", "location": "Ithaca, NY"},
                ],
            )
            rows = get_microhaplotype_accumulation_data(db, 1)

        self.assertEqual(
            [row["institution_label"] for row in rows],
            ["USDA ARS", "USDA ARS", "Cornell"],
        )
        self.assertEqual(
            [row["institution_location"] for row in rows],
            ["Geneva, NY", "Corvallis, OR", "Ithaca, NY"],
        )
        self.assertEqual(
            [row["institution_group_label"] for row in rows],
            [
                "USDA ARS (Geneva, NY)",
                "USDA ARS (Corvallis, OR)",
                "Cornell (Ithaca, NY)",
            ],
        )

    def test_project_sharing_data_uses_selectable_program_groups(self):
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
            default_summary = get_microhaplotype_project_sharing_data(db, 1)
            summary = get_microhaplotype_project_sharing_data(
                db,
                1,
                selected_group_ids=[
                    "validation",
                    "program:fallback-one:unknown-location",
                    "all",
                ],
            )
            expanded = get_microhaplotype_project_sharing_data(
                db,
                1,
                selected_group_ids=[
                    "validation",
                    "program:fallback-one:unknown-location",
                    "program:fallback-two:unknown-location",
                    "all",
                ],
            )
            constrained = get_microhaplotype_project_sharing_data(
                db,
                1,
                max_intersections=1,
                selected_group_ids=[
                    "validation",
                    "program:fallback-one:unknown-location",
                    "program:fallback-two:unknown-location",
                    "all",
                ],
            )

        self.assertEqual(
            [group["label"] for group in summary["available_owner_groups"]],
            ["Validation", "Fallback One", "Fallback Three", "Fallback Two", "Remaining Locations"],
        )
        self.assertEqual(len(default_summary["default_group_ids"]), 3)
        self.assertIn("validation", default_summary["default_group_ids"])
        self.assertNotIn("all", default_summary["default_group_ids"])
        self.assertEqual(
            sum(1 for group_id in default_summary["default_group_ids"] if group_id.startswith("program:")),
            2,
        )
        self.assertEqual(
            [group["label"] for group in summary["owner_groups"]],
            ["Validation", "Fallback One", "Remaining Locations"],
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
                (["validation", "program:fallback-one:unknown-location", "all"], 3, 2, "common"),
                (["validation", "program:fallback-one:unknown-location"], 2, 1, "rare"),
                (["all"], 1, 3, "private"),
                (["validation"], 1, 0, "private"),
                (["program:fallback-one:unknown-location"], 1, 0, "private"),
            ],
        )

        self.assertEqual(
            [group["label"] for group in expanded["owner_groups"]],
            ["Validation", "Fallback One", "Fallback Two", "Remaining Locations"],
        )
        self.assertEqual(
            sum(row["microhaplotype_count"] for row in expanded["intersections"]),
            6,
        )
        self.assertIn(
            {
                "group_ids": [
                    "program:fallback-two:unknown-location",
                    "all",
                ],
                "project_ids": [
                    "program:fallback-two:unknown-location",
                    "all",
                ],
                "project_count": 2,
                "microhaplotype_count": 1,
                "category": "rare",
            },
            expanded["intersections"],
        )
        self.assertTrue(
            all(
                any(row["group_ids"] == [group["group_id"]] for row in constrained["intersections"])
                for group in constrained["owner_groups"]
            )
        )

    def test_remaining_locations_includes_unselected_locations_on_selected_projects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "matrix.csv")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("AlleleID,E1,E2\n")

            sample_lookup = write_presence_lookup_artifact(
                [],
                [10, 20],
                [],
                entity_type="sample_lookup",
                species_id=1,
                source_path=source_path,
                output_dir=temp_dir,
            )
            project_lookup = write_presence_lookup_artifact(
                [
                    (10, 2),
                    (20, 3),
                ],
                [10, 20],
                [2, 3],
                entity_type="project_lookup",
                species_id=1,
                source_path=source_path,
                output_dir=temp_dir,
            )

            db = FakeAccumulationDb(
                sample_lookup["artifact_path"],
                project_lookup["artifact_path"],
                contact_rows=[
                    {"project_id": 2, "institution": "Fallback Two", "location": ""},
                    {"project_id": 2, "institution": "Fallback Three", "location": ""},
                ],
            )
            summary = get_microhaplotype_project_sharing_data(
                db,
                1,
                selected_group_ids=[
                    "program:fallback-two:unknown-location",
                    "all",
                ],
            )

        self.assertEqual(
            sum(row["microhaplotype_count"] for row in summary["intersections"]),
            2,
        )
        self.assertIn(
            {
                "group_ids": [
                    "program:fallback-two:unknown-location",
                    "all",
                ],
                "project_ids": [
                    "program:fallback-two:unknown-location",
                    "all",
                ],
                "project_count": 2,
                "microhaplotype_count": 1,
                "category": "common",
            },
            summary["intersections"],
        )


if __name__ == "__main__":
    unittest.main()
