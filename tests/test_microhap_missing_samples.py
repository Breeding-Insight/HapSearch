import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database.queries import get_microhaplotypes_paginated


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

    def test_zero_frequency_filter_excludes_missing_sample_context(self):
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
        self.assertIn(
            "AND EXISTS (SELECT 1 FROM samples s3 WHERE s3.species_id = sp.id)",
            executed_count_query,
        )

    def test_frequency_range_starting_at_zero_applies_missing_guard(self):
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
        self.assertIn(
            "AND EXISTS (SELECT 1 FROM samples s3 WHERE s3.species_id = sp.id)",
            executed_count_query,
        )

    def test_positive_frequency_range_does_not_apply_missing_guard(self):
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
        self.assertNotIn(
            "AND EXISTS (SELECT 1 FROM samples s3 WHERE s3.species_id = sp.id)",
            executed_count_query,
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
                freq_range=[0.0, 1.0],
                current_page=1,
            )

        rendered = repr(result)
        self.assertIn("Missing", rendered)
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
                freq_range=[0.0, 1.0],
                current_page=1,
            )

        self.assertIsNone(mock_paginated.call_args.kwargs["min_frequency"])
        self.assertIsNone(mock_paginated.call_args.kwargs["max_frequency"])

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


if __name__ == "__main__":
    unittest.main()
