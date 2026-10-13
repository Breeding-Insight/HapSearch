import unittest

from database.queries import get_botloci_count, is_bottom_locus
from scripts.import_botloci import parse_botloci_text


class FakeBotlociDb:
    def __init__(self, marker_ids=None, table_exists=True):
        self.marker_ids = set(marker_ids or [])
        self._table_exists = table_exists

    def table_exists(self, table_name):
        return table_name == "botloci" and self._table_exists

    def execute_query(self, query, params=()):
        if "COUNT(*)" in query:
            return [{"count": len(self.marker_ids)}]
        if "WHERE marker_id = ?" in query:
            marker_id = params[0]
            return [{"marker_id": marker_id}] if marker_id in self.marker_ids else []
        return []


class ParseBotlociTests(unittest.TestCase):
    def test_parse_ignores_blank_lines_and_trims_whitespace(self):
        text = "\n chr1.1_000194324 \n\nchr1.1_000309952\t\n"
        self.assertEqual(
            parse_botloci_text(text),
            ["chr1.1_000194324", "chr1.1_000309952"],
        )

    def test_parse_deduplicates_in_file_order(self):
        text = "chr1.1_000194324\nchr1.1_000309952\nchr1.1_000194324\n"
        self.assertEqual(
            parse_botloci_text(text),
            ["chr1.1_000194324", "chr1.1_000309952"],
        )


class BotlociLookupTests(unittest.TestCase):
    def test_missing_table_behaves_as_empty_top_strand_lookup(self):
        db = FakeBotlociDb(table_exists=False)
        self.assertEqual(get_botloci_count(db), 0)
        self.assertFalse(is_bottom_locus(db, "chr1.1_000194324"))

    def test_empty_lookup_is_top_strand_with_warning_needed(self):
        db = FakeBotlociDb()
        self.assertEqual(get_botloci_count(db), 0)
        self.assertFalse(is_bottom_locus(db, "chr1.1_000194324"))

    def test_marker_present_is_bottom_strand(self):
        db = FakeBotlociDb({"chr1.1_000194324"})
        self.assertEqual(get_botloci_count(db), 1)
        self.assertTrue(is_bottom_locus(db, "chr1.1_000194324"))

    def test_marker_absent_from_non_empty_lookup_is_top_strand(self):
        db = FakeBotlociDb({"chr1.1_000194324"})
        self.assertEqual(get_botloci_count(db), 1)
        self.assertFalse(is_bottom_locus(db, "chr1.1_000309952"))


if __name__ == "__main__":
    unittest.main()
