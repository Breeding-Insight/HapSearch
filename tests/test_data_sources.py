import os
import subprocess
import tempfile
import unittest

from scripts.build_database import (
    BuildError,
    DataSource,
    checkout_source,
    data_version,
    load_data_sources,
    parse_ref_overrides,
)

SOURCES = """
[[source]]
name = "alfalfa"
repo = "Breeding-Insight/alfalfa_haplotype_db"
ref = "hapsearch-v055"
link = "Breeding-Insight-alfalfa_haplotype_db"

[[source]]
name = "blueberry"
repo = "Breeding-Insight/blueberry_haplotype_db"
ref = "hapsearch-v002"
"""


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@example.org", "-c", "user.name=test", *args],
        cwd=cwd, check=True, capture_output=True,
    )


class DataSourcesTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.dir = temp_dir.name
        self.sources_path = os.path.join(self.dir, "data_sources.toml")
        with open(self.sources_path, "w", encoding="utf-8") as handle:
            handle.write(SOURCES)

    def test_pinned_refs_are_used(self):
        sources = load_data_sources(self.sources_path, {})

        self.assertEqual([(s.name, s.ref) for s in sources],
                         [("alfalfa", "hapsearch-v055"), ("blueberry", "hapsearch-v002")])
        self.assertEqual(sources[0].link, "Breeding-Insight-alfalfa_haplotype_db")

    def test_override_changes_only_that_source(self):
        sources = load_data_sources(self.sources_path, parse_ref_overrides(["blueberry=master"]))

        self.assertEqual([(s.name, s.ref) for s in sources],
                         [("alfalfa", "hapsearch-v055"), ("blueberry", "master")])

    def test_overrides_parse_commas_repeats_and_blanks(self):
        self.assertEqual(
            parse_ref_overrides(["alfalfa=master, blueberry=v3", "", "alfalfa=v056"]),
            {"alfalfa": "v056", "blueberry": "v3"},
        )
        self.assertEqual(parse_ref_overrides([""]), {})
        with self.assertRaisesRegex(BuildError, "name=ref"):
            parse_ref_overrides(["alfalfa"])

    def test_unknown_override_is_rejected(self):
        with self.assertRaisesRegex(BuildError, "Unknown source.*cranberry"):
            load_data_sources(self.sources_path, {"cranberry": "master"})

    def test_duplicate_and_incomplete_sources_are_rejected(self):
        with open(self.sources_path, "a", encoding="utf-8") as handle:
            handle.write('\n[[source]]\nname = "alfalfa"\nrepo = "x/y"\nref = "main"\n')
        with self.assertRaisesRegex(BuildError, "duplicate source names: alfalfa"):
            load_data_sources(self.sources_path, {})

        with open(self.sources_path, "w", encoding="utf-8") as handle:
            handle.write('[[source]]\nname = "alfalfa"\nrepo = "x/y"\n')
        with self.assertRaisesRegex(BuildError, "needs ref"):
            load_data_sources(self.sources_path, {})

    def test_checkout_fetches_the_pinned_tag_not_the_latest_commit(self):
        origin = os.path.join(self.dir, "origin")
        os.makedirs(origin)
        git(origin, "init", "-q", "-b", "master")
        with open(os.path.join(origin, "version.txt"), "w", encoding="utf-8") as handle:
            handle.write("v055\n")
        git(origin, "add", "-A")
        git(origin, "commit", "-qm", "v055 data")
        git(origin, "tag", "hapsearch-v055")
        with open(os.path.join(origin, "version.txt"), "w", encoding="utf-8") as handle:
            handle.write("v056 work in progress\n")
        git(origin, "commit", "-qam", "unfinished v056")

        cache = os.path.join(self.dir, "cache")
        pinned = checkout_source(DataSource(name="alfalfa", path="", repo=origin,
                                            ref="hapsearch-v055"), cache)
        with open(os.path.join(pinned.path, "version.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "v055\n")

        latest = checkout_source(DataSource(name="alfalfa", path="", repo=origin,
                                            ref="master"), cache)
        with open(os.path.join(latest.path, "version.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "v056 work in progress\n")
        self.assertNotEqual(pinned.commit, latest.commit)
        self.assertEqual(data_version([latest]), f"alfalfa=master@{latest.commit[:12]}")

    def test_missing_ref_fails_clearly(self):
        origin = os.path.join(self.dir, "origin")
        os.makedirs(origin)
        git(origin, "init", "-q", "-b", "master")
        git(origin, "commit", "-q", "--allow-empty", "-m", "start")

        with self.assertRaisesRegex(BuildError, "git fetch"):
            checkout_source(DataSource(name="alfalfa", path="", repo=origin,
                                       ref="no-such-tag"), os.path.join(self.dir, "cache"))


if __name__ == "__main__":
    unittest.main()
