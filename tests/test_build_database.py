import os
import tempfile
import unittest

from scripts.build_database import BuildError, fasta_stem, find_manifest, load_plan

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

    def test_finds_manifest_in_root_data_hapsearch_folder(self):
        root_hapsearch = os.path.join(self.repo, "data", "hapSearch")
        os.makedirs(root_hapsearch)
        os.remove(self.manifest)
        self._touch(os.path.join(root_hapsearch, "manifest.toml"))

        self.assertEqual(
            find_manifest(self.repo, None), os.path.join(root_hapsearch, "manifest.toml")
        )

    def test_missing_repo_is_explained(self):
        with self.assertRaisesRegex(BuildError, "Data repository not found"):
            find_manifest(os.path.join(self.repo, "missing"), None)


PATTERN_MANIFEST = """
[metadata]
project_mapping = "HapSearch_mapping.csv"
owner_contacts = "HapSearch_owner_contacts.csv"

[[species]]
name = "Medicago sativa"
fasta = "/db/alfalfa_allele_db_v*.fa"
botloci = "*.botloci"
sample_presence = "Sample_hapStatus"
project_presence = "hapPA/{fasta}_hapPA_matrix.csv"
"""


class PatternManifestTests(BuildPlanTests):
    def setUp(self):
        super().setUp()
        for version in ("v053", "v054", "v099", "v100"):
            self._touch(os.path.join(self.repo, "db", f"alfalfa_allele_db_{version}.fa"))
        for version in ("v054", "v100"):
            self._touch(os.path.join(self.hapsearch, "hapPA", f"alfalfa_allele_db_{version}_hapPA_matrix.csv"))
        self._touch(os.path.join(self.hapsearch, "probes.botloci"))
        self._write_manifest(PATTERN_MANIFEST)

    def _write_manifest(self, text):
        with open(self.manifest, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _plan(self):
        return load_plan(self.repo, os.path.join(self.repo, ".cache"))

    # The parent's exact-path tests do not apply to this manifest.
    test_paths_resolve_from_manifest_folder_and_repo_root = None
    test_missing_input_names_the_file = None

    def test_newest_fasta_and_its_matrix_are_chosen(self):
        plan = self._plan()
        species = plan.species[0]

        self.assertEqual(os.path.basename(species.fasta), "alfalfa_allele_db_v100.fa")
        self.assertEqual(
            [os.path.basename(path) for path in species.project_presence],
            ["alfalfa_allele_db_v100_hapPA_matrix.csv"],
        )
        self.assertEqual(os.path.basename(species.botloci), "probes.botloci")
        self.assertEqual(plan.sources["Medicago sativa FASTA"], "db/alfalfa_allele_db_v100.fa")

    def test_newest_fasta_without_matrix_stops_the_build(self):
        os.remove(os.path.join(self.hapsearch, "hapPA", "alfalfa_allele_db_v100_hapPA_matrix.csv"))

        with self.assertRaisesRegex(BuildError, "alfalfa_allele_db_v100_hapPA_matrix.csv.*v100.fa"):
            self._plan()

    def test_pinned_fasta_selects_matching_matrix(self):
        self._write_manifest(PATTERN_MANIFEST.replace("alfalfa_allele_db_v*.fa", "alfalfa_allele_db_v054.fa"))

        species = self._plan().species[0]

        self.assertEqual(
            [os.path.basename(path) for path in species.project_presence],
            ["alfalfa_allele_db_v054_hapPA_matrix.csv"],
        )

    def test_ambiguous_single_file_pattern_stops_the_build(self):
        self._touch(os.path.join(self.hapsearch, "old_probes.botloci"))

        with self.assertRaisesRegex(BuildError, "matches 2 files"):
            self._plan()

    def test_fasta_stem_strips_compound_extensions(self):
        self.assertEqual(fasta_stem("/x/alfalfa_allele_db_v055.fa.gz"), "alfalfa_allele_db_v055")


VERSION_MANIFEST = """
[metadata]
project_mapping = "HapSearch_mapping.csv"
owner_contacts = "HapSearch_owner_contacts.csv"

[[species]]
name = "Medicago sativa"
fasta = "/db/alfalfa_allele_db_{version}.fa"
project_presence = "hapPA/{fasta}_hapPA_matrix.csv"
"""


class VersionPinTests(PatternManifestTests):
    """The FASTA version (e.g. v055) selects the FASTA and its matrix."""

    def setUp(self):
        super().setUp()
        # Look-alike files that must never be picked as a version.
        for name in ("alfalfa_allele_db_v016_81bp.fa", "alfalfa_allele_db_v042_ActualAmpliconSeq.fa",
                     "alfalfa_allele_db_v100.fa.self.bn"):
            self._touch(os.path.join(self.repo, "db", name))
        self._write_manifest(VERSION_MANIFEST)

    def _plan(self, version=None):
        return load_plan(self.repo, os.path.join(self.repo, ".cache"), version=version)

    # Inherited pattern tests use a different manifest.
    test_newest_fasta_and_its_matrix_are_chosen = None
    test_newest_fasta_without_matrix_stops_the_build = None
    test_pinned_fasta_selects_matching_matrix = None
    test_ambiguous_single_file_pattern_stops_the_build = None

    def test_pinned_version_selects_fasta_and_matrix(self):
        species = self._plan("v054").species[0]

        self.assertEqual(os.path.basename(species.fasta), "alfalfa_allele_db_v054.fa")
        self.assertEqual(
            [os.path.basename(path) for path in species.project_presence],
            ["alfalfa_allele_db_v054_hapPA_matrix.csv"],
        )

    def test_unpinned_uses_newest_real_version(self):
        species = self._plan().species[0]

        self.assertEqual(os.path.basename(species.fasta), "alfalfa_allele_db_v100.fa")

    def test_missing_version_lists_what_exists(self):
        with self.assertRaisesRegex(BuildError, "version v056 not found.*v100"):
            self._plan("v056")

    def test_version_needs_placeholder_in_manifest(self):
        self._write_manifest(VERSION_MANIFEST.replace("{version}", "v054"))

        with self.assertRaisesRegex(BuildError, "no \\{version\\} placeholder"):
            self._plan("v054")


if __name__ == "__main__":
    unittest.main()
