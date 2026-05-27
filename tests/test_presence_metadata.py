import os
import tempfile
import unittest

from scripts.presence_metadata import (
    genotyping_sources_match,
    get_mapping_for_project_code,
    load_owner_contacts,
    load_project_mapping,
    normalize_project_code,
    pick_mapping_for_source,
    parse_project_header,
    parse_sample_filename_context,
    resolve_project_record,
)


class PresenceMetadataTests(unittest.TestCase):
    def test_single_dai_mapping(self):
        parsed = parse_project_header("P01_Debby_ProjectX_DAl21-6679")
        self.assertEqual(parsed["genotyping_source"], "DAl21-6679")

    def test_multi_dai_validation_group(self):
        ctx = parse_sample_filename_context(
            "/tmp/DAl21-5779_DAl21-6024_madc_all4plates_validation_hapStatus.csv"
        )
        self.assertTrue(ctx["is_validation"])
        self.assertEqual(ctx["genotyping_source"], "DAl21-5779_DAl21-6024")

    def test_missing_fields_warn_blank(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write("genotyping_source,project_code,owner_name\nDAl21-6679,P01_Debby_Zhanyou_digestibility_16plates_DAl21-6679,Debby\n")
            temp_path = handle.name
        try:
            loaded = load_project_mapping(temp_path)
            self.assertIn("project_name", loaded.missing_optional_columns)
            self.assertEqual(
                loaded.by_project_code["P01_Debby_Zhanyou_digestibility_16plates_DAl21-6679"]["owner_name"],
                "Debby",
            )
        finally:
            os.remove(temp_path)

    def test_backfill_record_prefers_metadata(self):
        parsed = parse_project_header("P01_Unknown_DAl21-6679")
        mapping_row = {
            "genotyping_source": "DAl21-6679",
            "project_code": "P01_Unknown_DAl21-6679",
            "owner_name": "Debby",
            "project_name": "Digestibility",
            "description": "from mapping",
            "start_date": "",
            "is_sample_default": "",
        }
        contacts = {
            "debby": {
                "owner_name": "Debby",
                "pi_name": "Debby",
                "pi_email": "debby@example.com",
                "pi_institution": "UW",
                "pi_department": "Plant Science",
            }
        }
        resolved = resolve_project_record(parsed, mapping_row, contacts)
        self.assertEqual(resolved["pi_name"], "Debby")
        self.assertEqual(resolved["project_name"], "Digestibility")
        self.assertIn("genotyping_source=DAl21-6679", resolved["description"])

    def test_owner_contacts_load(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write("owner_name,pi_email,pi_institution,pi_department\nDebby,debby@example.com,UW,Plant Science\n")
            temp_path = handle.name
        try:
            loaded = load_owner_contacts(temp_path)
            self.assertEqual(loaded.by_owner_name["debby"]["pi_email"], "debby@example.com")
        finally:
            os.remove(temp_path)

    def test_resolve_project_record_does_not_use_header_owner_without_mapping_owner(self):
        parsed = parse_project_header("P01_HeaderOwner_ProjectX_DAl21-6679")
        mapping_row = {
            "genotyping_source": "DAl21-6679",
            "project_code": "P01_HeaderOwner_ProjectX_DAl21-6679",
            "owner_name": "",
            "project_name": "ProjectX",
            "description": "",
            "start_date": "",
            "is_sample_default": "",
        }
        resolved = resolve_project_record(parsed, mapping_row, {})
        self.assertEqual(resolved["pi_name"], "")

    def test_pick_mapping_for_source(self):
        rows = {
            "DAl21-6679": [
                {"genotyping_source": "DAl21-6679", "project_code": "P01_x", "is_sample_default": ""},
                {"genotyping_source": "DAl21-6679", "project_code": "P01_default", "is_sample_default": "1"},
            ]
        }
        selected = pick_mapping_for_source("DAl21-6679", rows)
        self.assertEqual(selected["project_code"], "P01_default")

    def test_pick_mapping_for_source_with_context_disambiguates_same_order(self):
        rows = {
            "DAl22-7011": [
                {
                    "genotyping_source": "DAl22-7011",
                    "project_code": "P02_Brian_DAl22-7011",
                    "owner_name": "Brian Irish",
                    "owner_names": ["Brian Irish"],
                    "project_name": "Brian Study",
                    "is_sample_default": "",
                },
                {
                    "genotyping_source": "DAl22-7011",
                    "project_code": "P04_Longxi_DAl22-7011",
                    "owner_name": "Long-Xi Yu",
                    "owner_names": ["Long-Xi Yu"],
                    "project_name": "Longxi Study",
                    "is_sample_default": "",
                },
            ]
        }
        selected = pick_mapping_for_source(
            "DAl22-7011",
            rows,
            context_text="DAl22-7011_MADC_Report_merged_rename_updatedSeq_Long-Xi_filter_miss_hapStatus.csv",
        )
        self.assertEqual(selected["project_code"], "P04_Longxi_DAl22-7011")

    def test_resolve_project_record_forced_project_code_wins(self):
        parsed = parse_project_header("P99_Something_DAl21-6679")
        mapping_row = {
            "genotyping_source": "DAl21-6679",
            "project_code": "P99_Something_DAl21-6679",
            "owner_name": "Debby",
            "project_name": "Digestibility",
            "description": "",
            "start_date": "",
            "is_sample_default": "",
        }
        resolved = resolve_project_record(
            parsed,
            mapping_row,
            {},
            forced_project_code="P01_Debby_Zhanyou_digestibility_16plates_DAl21-6679",
        )
        self.assertEqual(resolved["project_code"], "P01_Debby_Zhanyou_digestibility_16plates_DAl21-6679")

    def test_genotyping_sources_match_normalized(self):
        self.assertTrue(genotyping_sources_match("DAI22-7011", "DAl22-7011"))
        self.assertFalse(genotyping_sources_match("DAl22-7011", "DAl22-7249"))

    def test_normalize_project_code_converts_word_dashes_not_dai_dash(self):
        self.assertEqual(
            normalize_project_code("P07_Debby-winterSurv_16plates_DAl22-7513"),
            "P07_Debby_winterSurv_16plates_DAl22-7513",
        )

    def test_get_mapping_for_project_code_dash_underscore_equivalence(self):
        mapping = {
            "P07_Debby_winterSurv_16plates_DAl22-7513": {
                "project_code": "P07_Debby_winterSurv_16plates_DAl22-7513",
            }
        }
        hit = get_mapping_for_project_code("P07_Debby-winterSurv_16plates_DAl22-7513", mapping)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["project_code"], "P07_Debby_winterSurv_16plates_DAl22-7513")

    def test_multi_owner_mapping_semicolon(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write(
                "genotyping_source,project_code,owner_name\n"
                "DAl22-7011,P02_Brian_DAl22-7011,Brian Jones; Heathcliffe Brown\n"
            )
            temp_path = handle.name
        try:
            loaded = load_project_mapping(temp_path)
            row = loaded.by_project_code["P02_Brian_DAl22-7011"]
            self.assertEqual(row["owner_names"], ["Brian Jones", "Heathcliffe Brown"])
            self.assertEqual(row["owner_name"], "Brian Jones")
        finally:
            os.remove(temp_path)

    def test_airtable_style_contacts(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write(
                "Full Name,Primary Email,Employer,Position\n"
                "Brian Jones,brian@example.com,UW Madison,Plant Science\n"
            )
            temp_path = handle.name
        try:
            loaded = load_owner_contacts(temp_path)
            self.assertIn("brian jones", loaded.by_owner_name)
            self.assertEqual(loaded.by_owner_name["brian jones"]["pi_email"], "brian@example.com")
            self.assertEqual(loaded.by_owner_name["brian jones"]["pi_institution"], "UW Madison")
        finally:
            os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
