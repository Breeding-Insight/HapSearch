import unittest

from scripts.import_project_presence import validate_project_columns_against_mapping


class ProjectImportValidationTests(unittest.TestCase):
    def test_unmapped_project_column_raises(self):
        mapping_by_project_code = {
            "P02_Brian_DAl22-7011": {"project_code": "P02_Brian_DAl22-7011", "genotyping_source": "DAl22-7011"},
            "P04_Longxi_DAl22-7011": {"project_code": "P04_Longxi_DAl22-7011", "genotyping_source": "DAl22-7011"},
        }

        with self.assertRaises(ValueError) as ctx:
            validate_project_columns_against_mapping(
                ["P02_Brian_DAl22-7011", "P02_Heathcliffe_DAl22-7011"],
                mapping_by_project_code,
            )
        self.assertIn("Unmapped columns", str(ctx.exception))
        self.assertIn("P02_Heathcliffe_DAl22-7011", str(ctx.exception))

    def test_mapping_source_mismatch_raises(self):
        mapping_by_project_code = {
            "P02_Brian_DAl22-7011": {"project_code": "P02_Brian_DAl22-7011", "genotyping_source": "DAl22-7249"},
        }

        with self.assertRaises(ValueError) as ctx:
            validate_project_columns_against_mapping(
                ["P02_Brian_DAl22-7011"],
                mapping_by_project_code,
            )
        self.assertIn("Mismatches", str(ctx.exception))
        self.assertIn("DAl22-7249", str(ctx.exception))

    def test_exact_project_code_mapping_allows_multiple_projects_same_order(self):
        mapping_by_project_code = {
            "P02_Brian_DAl22-7011": {"project_code": "P02_Brian_DAl22-7011", "genotyping_source": "DAl22-7011"},
            "P02_Heathcliffe_DAl22-7011": {
                "project_code": "P02_Heathcliffe_DAl22-7011",
                "genotyping_source": "DAl22-7011",
            },
            "P04_Longxi_DAl22-7011": {"project_code": "P04_Longxi_DAl22-7011", "genotyping_source": "DAl22-7011"},
        }

        # Should not raise: each project code maps directly even though source key is shared.
        validate_project_columns_against_mapping(
            ["P02_Brian_DAl22-7011", "P02_Heathcliffe_DAl22-7011", "P04_Longxi_DAl22-7011"],
            mapping_by_project_code,
        )

    def test_dash_underscore_project_code_variants_validate(self):
        mapping_by_project_code = {
            "P10_Heathcliffe_GWAS_10plates_DAl22-7534": {
                "project_code": "P10_Heathcliffe_GWAS_10plates_DAl22-7534",
                "genotyping_source": "DAl22-7534",
            },
            "P14_Salinity_Devinder_2plates_DAl23-8561": {
                "project_code": "P14_Salinity_Devinder_2plates_DAl23-8561",
                "genotyping_source": "DAl23-8561",
            },
        }
        validate_project_columns_against_mapping(
            ["P10_Heathcliffe-GWAS_10plates_DAl22-7534", "P14_Salinity-Devinder_2plates_DAl23-8561"],
            mapping_by_project_code,
        )


if __name__ == "__main__":
    unittest.main()
