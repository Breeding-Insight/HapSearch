import unittest

from pages.export_controls import clean_filename


class CleanFilenameTest(unittest.TestCase):
    def test_keeps_a_plain_name(self):
        self.assertEqual(
            clean_filename("multiple-sequence-alignment-pecanChr01_000347990", "x", "png"),
            "multiple-sequence-alignment-pecanChr01_000347990",
        )

    def test_drops_the_extension_the_user_typed(self):
        self.assertEqual(clean_filename("my_samples.CSV", "x", "csv"), "my_samples")

    def test_keeps_other_dots(self):
        self.assertEqual(clean_filename("chr1.1_000194324", "x", "png"), "chr1.1_000194324")

    def test_replaces_characters_file_systems_reject(self):
        self.assertEqual(
            clean_filename('chr1.1_000194324|Alt 0002/samples', "x", "csv"),
            "chr1.1_000194324_Alt_0002_samples",
        )

    def test_falls_back_when_empty(self):
        self.assertEqual(clean_filename("   ", "default_name", "png"), "default_name")
        self.assertEqual(clean_filename(None, "default_name", "png"), "default_name")
        self.assertEqual(clean_filename(".png", "default_name", "png"), "default_name")


if __name__ == "__main__":
    unittest.main()
