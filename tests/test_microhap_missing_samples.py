import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database.queries import (
    _get_microhaplotype_ids_for_sample_filter_artifacts,
    get_microhaplotypes_paginated,
)


class FakeDb:
    def shared_connection(self):
        return nullcontext()


class MicrohapMissingSampleTests(unittest.TestCase):
    def _import_explorer_or_skip(self):
        try:
            from pages import haplotype_explorer as explorer
        except ModuleNotFoundError as exc:
            self.skipTest(f"Dash dependencies are unavailable in this environment: {exc}")
        return explorer

    def test_zero_frequency_filter_keeps_missing_sample_context(self):
        db = MagicMock()
        db.execute_query.side_effect = [[{"total": 0}], []]

        get_microhaplotypes_paginated(
            db,
            min_frequency=0.0,
            max_frequency=0.0,
            page=1,
            per_page=25,
        )

        executed_count_query = db.execute_query.call_args_list[0][0][0]
        self.assertNotIn(
            "AND EXISTS (SELECT 1 FROM samples s3 WHERE s3.species_id = sp.id)",
            executed_count_query,
        )

    def test_frequency_range_starting_at_zero_keeps_missing_sample_context(self):
        db = MagicMock()
        db.execute_query.side_effect = [[{"total": 0}], []]

        get_microhaplotypes_paginated(
            db,
            min_frequency=0.0,
            max_frequency=0.25,
            page=1,
            per_page=25,
        )

        executed_count_query = db.execute_query.call_args_list[0][0][0]
        self.assertNotIn(
            "AND EXISTS (SELECT 1 FROM samples s3 WHERE s3.species_id = sp.id)",
            executed_count_query,
        )

    def test_positive_frequency_range_applies_missing_guard(self):
        db = MagicMock()
        db.execute_query.side_effect = [[{"total": 0}], []]

        get_microhaplotypes_paginated(
            db,
            min_frequency=0.01,
            max_frequency=0.25,
            page=1,
            per_page=25,
        )

        executed_count_query = db.execute_query.call_args_list[0][0][0]
        self.assertIn(
            "AND EXISTS (SELECT 1 FROM samples s3 WHERE s3.species_id = sp.id)",
            executed_count_query,
        )
        self.assertIn("AND COALESCE(m.sample_count, 0) > 0", executed_count_query)

    def test_exclude_missing_samples_applies_missing_guard_without_frequency_filter(self):
        db = MagicMock()
        db.execute_query.side_effect = [[{"total": 0}], []]

        get_microhaplotypes_paginated(
            db,
            exclude_missing_samples=True,
            page=1,
            per_page=25,
        )

        executed_count_query = db.execute_query.call_args_list[0][0][0]
        self.assertIn(
            "AND EXISTS (SELECT 1 FROM samples s3 WHERE s3.species_id = sp.id)",
            executed_count_query,
        )
        self.assertIn("AND COALESCE(m.sample_count, 0) > 0", executed_count_query)

    def test_sample_artifact_filter_does_not_truncate_after_sql_param_limit(self):
        db = MagicMock()
        db.execute_query.side_effect = [
            [{"id": 99}],
            [{"artifact_path": "/tmp/sample_lookup.npz"}],
        ]

        with patch(
            "database.queries.read_microhaplotype_ids_for_entity",
            return_value=list(range(1, 1803)),
        ):
            ids = _get_microhaplotype_ids_for_sample_filter_artifacts(
                db,
                "R_6410",
                species_id=1,
            )

        self.assertEqual(len(ids), 1802)
        self.assertEqual(ids[-1], 1802)

    def test_sample_filter_uses_chunked_queries_when_artifact_ids_exceed_param_limit(self):
        db = MagicMock()
        db.execute_query.side_effect = [
            [{"id": 2, "haplotype_name": "B"}],
            [{"id": 1802, "haplotype_name": "A"}],
        ]

        with patch(
            "database.queries._get_microhaplotype_ids_for_sample_filter_artifacts",
            return_value=list(range(1, 1803)),
        ):
            result = get_microhaplotypes_paginated(
                db,
                species_id=1,
                sample_filter="R_6410",
                min_frequency=0.0,
                max_frequency=0.0026,
                page=1,
                per_page=25,
            )

        self.assertEqual(result["total"], 2)
        self.assertEqual([row["haplotype_name"] for row in result["microhaplotypes"]], ["A", "B"])
        self.assertEqual(db.execute_query.call_count, 2)
        self.assertIn(1802, db.execute_query.call_args_list[1][0][1])
        self.assertTrue(
            all(len(call_args[0][1]) <= 1800 for call_args in db.execute_query.call_args_list)
        )

    def test_search_results_label_missing_when_species_has_no_samples(self):
        explorer = self._import_explorer_or_skip()
        with patch.object(explorer, "DatabaseManager", return_value=FakeDb()), patch.object(
            explorer,
            "get_presence_statistics",
            return_value={"present_samples": 0, "total_samples": 10, "presence_frequency": 0.0},
        ), patch.object(
            explorer,
            "get_microhaplotypes_paginated",
            return_value={
                "microhaplotypes": [
                    {
                        "haplotype_name": "H1",
                        "frequency": 0.0,
                        "sample_count": 0,
                        "species_sample_count": 0,
                    }
                ],
                "total": 1,
                "page": 1,
                "per_page": 7,
                "total_pages": 1,
            },
        ):
            result = explorer.search_haplotypes(
                seq_search=None,
                species_id=1,
                marker_filter=None,
                chromosome_id=None,
                sample_filter=None,
                freq_range=[0.0, 100.0],
                exclude_missing_samples=[],
                current_page=1,
            )

        rendered = repr(result)
        self.assertIn("Missing", rendered)
        self.assertIn("Freq: NA", rendered)
        self.assertNotIn("0 samples", rendered)

    def test_default_frequency_slider_applies_no_backend_bounds(self):
        explorer = self._import_explorer_or_skip()
        with patch.object(explorer, "DatabaseManager", return_value=FakeDb()), patch.object(
            explorer,
            "get_microhaplotypes_paginated",
            return_value={
                "microhaplotypes": [],
                "total": 0,
                "page": 1,
                "per_page": 7,
                "total_pages": 0,
            },
        ) as mock_paginated:
            explorer.search_haplotypes(
                seq_search=None,
                species_id=1,
                marker_filter=None,
                chromosome_id=None,
                sample_filter=None,
                freq_range=[0.0, 100.0],
                exclude_missing_samples=[],
                current_page=1,
            )

        self.assertIsNone(mock_paginated.call_args.kwargs["min_frequency"])
        self.assertIsNone(mock_paginated.call_args.kwargs["max_frequency"])
        self.assertFalse(mock_paginated.call_args.kwargs["exclude_missing_samples"])

    def test_piecewise_frequency_slider_resolves_low_end_values(self):
        explorer = self._import_explorer_or_skip()

        self.assertEqual(explorer._resolve_frequency_bounds([0, 5]), (0.0, 0.001))
        self.assertEqual(explorer._resolve_frequency_bounds([0, 25]), (0.0, 0.005))
        self.assertEqual(explorer._resolve_frequency_bounds([0, 50]), (0.0, 0.01))

    def test_numeric_frequency_values_map_to_piecewise_slider_positions(self):
        explorer = self._import_explorer_or_skip()

        self.assertEqual(explorer._frequency_to_slider_position(0.001), 5.0)
        self.assertEqual(explorer._frequency_to_slider_position(0.005), 25.0)
        self.assertEqual(explorer._frequency_to_slider_position(0.01), 50.0)

    def test_detail_panel_uses_missing_for_samples_when_species_has_none(self):
        explorer = self._import_explorer_or_skip()
        fake_ctx = SimpleNamespace(
            triggered_id={"type": "haplotype-list-item", "index": "H1"},
            triggered=[{"prop_id": "dummy"}],
        )
        with patch.object(explorer, "DatabaseManager", return_value=FakeDb()), patch.object(
            explorer,
            "get_microhaplotype_details",
            return_value={
                "haplotype_name": "H1",
                "marker_id": "M1",
                "haplotype_sequence": "ACTG",
                "frequency": 0.0,
                "species_id": 99,
            },
        ), patch.object(explorer, "get_samples_for_microhaplotype", return_value=[]), patch.object(
            explorer, "get_projects_for_microhaplotype", return_value=[]
        ), patch.object(
            explorer, "get_projects_for_allele_presence", return_value=[]
        ), patch.object(
            explorer, "get_projects_for_sample_presence", return_value=[]
        ), patch.object(
            explorer, "get_contacts_for_projects", return_value=[]
        ), patch.object(
            explorer, "get_samples_for_allele", return_value=[]
        ), patch.object(
            explorer,
            "get_presence_statistics",
            return_value={"present_samples": 0, "total_samples": 50, "presence_frequency": 0.0},
        ), patch.object(
            explorer, "get_species_sample_count", return_value=0
        ), patch.object(explorer, "ctx", fake_ctx):
            detail, _, _, toggle_children, _ = explorer.show_haplotype_details(
                n_clicks=[1],
                navigate_data=None,
                current_details=None,
            )

        self.assertEqual(toggle_children[1], "Samples (Missing samples)")
        self.assertIn("Missing", repr(detail))
        self.assertIn("NA", repr(detail))


if __name__ == "__main__":
    unittest.main()
