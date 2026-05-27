import unittest

from database.queries import _parse_dal_key, _build_dal_sort_expr


class ParseDalKeyTests(unittest.TestCase):
    def test_standard_description(self):
        desc = "internal_project_id=P01; genotyping_source=DAl21-6679; raw_header=P01_Debby"
        self.assertEqual(_parse_dal_key(desc), (21, 6679))

    def test_multi_source_takes_first(self):
        desc = "genotyping_source=DAl21-5779_DAl21-6024; raw_header=..."
        self.assertEqual(_parse_dal_key(desc), (21, 5779))

    def test_no_genotyping_source(self):
        desc = "internal_project_id=P99; raw_header=Validation"
        self.assertIsNone(_parse_dal_key(desc))

    def test_none_description(self):
        self.assertIsNone(_parse_dal_key(None))

    def test_empty_description(self):
        self.assertIsNone(_parse_dal_key(""))


class BuildDalSortExprTests(unittest.TestCase):
    def test_empty_rows_returns_column(self):
        self.assertEqual(_build_dal_sort_expr([]), "ss.project_id")

    def test_single_project_returns_column(self):
        rows = [{"project_id": 1, "description": "genotyping_source=DAl21-6679"}]
        self.assertEqual(_build_dal_sort_expr(rows), "ss.project_id")

    def test_parseable_sorted_by_dal(self):
        rows = [
            {"project_id": 10, "description": "genotyping_source=DAl22-7011"},
            {"project_id": 5, "description": "genotyping_source=DAl21-5779"},
            {"project_id": 8, "description": "genotyping_source=DAl21-6679"},
        ]
        expr = _build_dal_sort_expr(rows)
        self.assertIn("CASE", expr)
        # DAl21-5779 (pid=5) < DAl21-6679 (pid=8) < DAl22-7011 (pid=10)
        self.assertIn("WHEN 5 THEN 1", expr)
        self.assertIn("WHEN 8 THEN 2", expr)
        self.assertIn("WHEN 10 THEN 3", expr)

    def test_non_parseable_sorted_last(self):
        rows = [
            {"project_id": 3, "description": "raw_header=Validation"},
            {"project_id": 5, "description": "genotyping_source=DAl21-5779"},
            {"project_id": 7, "description": None},
        ]
        expr = _build_dal_sort_expr(rows)
        # pid=5 is parseable -> position 1
        # pid=3 and pid=7 non-parseable -> positions 2, 3 (sorted by id)
        self.assertIn("WHEN 5 THEN 1", expr)
        self.assertIn("WHEN 3 THEN 2", expr)
        self.assertIn("WHEN 7 THEN 3", expr)

    def test_all_non_parseable_still_builds_case(self):
        rows = [
            {"project_id": 2, "description": "raw_header=Foo"},
            {"project_id": 4, "description": "raw_header=Bar"},
        ]
        expr = _build_dal_sort_expr(rows)
        self.assertIn("WHEN 2 THEN 1", expr)
        self.assertIn("WHEN 4 THEN 2", expr)

    def test_custom_column_name(self):
        rows = [
            {"project_id": 1, "description": "genotyping_source=DAl21-5779"},
            {"project_id": 2, "description": "genotyping_source=DAl22-7011"},
        ]
        expr = _build_dal_sort_expr(rows, col="p.id")
        self.assertTrue(expr.startswith("CASE p.id"))


if __name__ == "__main__":
    unittest.main()
