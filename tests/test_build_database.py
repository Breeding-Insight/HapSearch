import os
import tempfile
import unittest

from scripts.build_database import BuildError, find_manifest, load_plan

MANIFEST = """
[metadata]
project_mapping = "HapSearch_mapping.csv"
owner_contacts = "HapSearch_owner_contacts.csv"

[[species]]
name = "Medicago sativa"
common_name = "Alfalfa"
fasta = "/db/alfalfa_allele_db_v055.fa"
sample_presence = "Sample_hapStatus"
project_presence = ["hapPA/alfalfa_allele_db_v055_hapPA_matrix.csv"]
"""


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.repo = temp_dir.name
        self.hapsearch = os.path.join(self.repo, "alfalfa", "data", "hapSearch")
        for folder in ("Sample_hapStatus", "hapPA"):
            os.makedirs(os.path.join(self.hapsearch, folder))
        os.makedirs(os.path.join(self.repo, "db"))
        for path in (
            "HapSearch_mapping.csv",
            "HapSearch_owner_contacts.csv",
            "Sample_hapStatus/DAl21-6679_hapStatus.csv",
            "Sample_hapStatus/DAl22-7249_hapStatus.csv.gz",
            "Sample_hapStatus/notes.txt",
            "hapPA/alfalfa_allele_db_v055_hapPA_matrix.csv",
        ):
            self._touch(os.path.join(self.hapsearch, path))
        self._touch(os.path.join(self.repo, "db", "alfalfa_allele_db_v055.fa"))
        self.manifest = os.path.join(self.hapsearch, "manifest.toml")
        with open(self.manifest, "w", encoding="utf-8") as handle:
            handle.write(MANIFEST)

    @staticmethod
    def _touch(path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x\n")

    def test_finds_manifest_under_species_hapsearch_folder(self):
        self.assertEqual(find_manifest(self.repo, None), self.manifest)

    def test_paths_resolve_from_manifest_folder_and_repo_root(self):
        plan = load_plan(self.repo, os.path.join(self.repo, ".cache"))
        species = plan.species[0]

        self.assertEqual(species.fasta, os.path.join(self.repo, "db", "alfalfa_allele_db_v055.fa"))
        self.assertEqual(
            [os.path.basename(path) for path in species.sample_presence],
            ["DAl21-6679_hapStatus.csv", "DAl22-7249_hapStatus.csv.gz"],
        )
        self.assertEqual(
            species.project_presence,
            [os.path.join(self.hapsearch, "hapPA", "alfalfa_allele_db_v055_hapPA_matrix.csv")],
        )
        self.assertEqual(
            plan.project_mapping, os.path.join(self.hapsearch, "HapSearch_mapping.csv")
        )

    def test_missing_input_names_the_file(self):
        os.remove(os.path.join(self.repo, "db", "alfalfa_allele_db_v055.fa"))

        with self.assertRaisesRegex(BuildError, "alfalfa_allele_db_v055.fa"):
            load_plan(self.repo, os.path.join(self.repo, ".cache"))

    def test_missing_repo_is_explained(self):
        with self.assertRaisesRegex(BuildError, "Data repository not found"):
            find_manifest(os.path.join(self.repo, "missing"), None)


if __name__ == "__main__":
    unittest.main()
