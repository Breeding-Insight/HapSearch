import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from flask import Flask, session

from auth import access
from auth.user_store import FirestoreUserStore, SqliteUserStore, normalize_species
from database.db_manager import DatabaseManager
from database.queries import get_database_statistics
from tests.test_user_store import ORCID_A, FakeFirestoreClient

APPLE, PECAN = 1, 2


def make_db(test):
    temp_dir = tempfile.TemporaryDirectory()
    test.addCleanup(temp_dir.cleanup)
    db = DatabaseManager(db_path=os.path.join(temp_dir.name, "hap.db"), read_only=False)
    db.ensure_schema()
    db.execute_update("INSERT INTO species (id, name, common_name) VALUES (1, 'Malus domestica', 'Apple')")
    db.execute_update("INSERT INTO species (id, name, common_name) VALUES (2, 'Carya illinoinensis', 'Pecan')")
    for species_id, marker, hap in ((APPLE, "appleChr01_100", "appleChr01_100|Ref_0001"),
                                    (PECAN, "pecanChr01_200", "pecanChr01_200|Ref_0001")):
        db.execute_update(
            "INSERT INTO chromosomes (id, species_id, chromosome_name) VALUES (?, ?, 'Chr01')",
            (species_id, species_id))
        db.execute_update(
            "INSERT INTO markers (id, marker_id, chromosome_id, position_start, position_end) "
            "VALUES (?, ?, ?, 1, 2)", (species_id, marker, species_id))
        db.execute_update(
            "INSERT INTO microhaplotypes (marker_id, haplotype_sequence, haplotype_name) "
            "VALUES (?, 'ACGT', ?)", (species_id, hap))
    db.execute_update("INSERT INTO projects (id, project_code, project_name) VALUES (1, 'P1', 'One')")
    db.execute_update("INSERT INTO samples (sample_code, project_id, species_id) VALUES ('s1', 1, 2)")
    return db


def entry(comp_id, prop, value):
    return {"id": comp_id, "property": prop, "value": value}


class SpeciesListStorageTests(unittest.TestCase):
    def test_names_are_trimmed_deduplicated_and_sorted(self):
        self.assertEqual(normalize_species([" Pecan", "apple", "PECAN", ""]), ["apple", "Pecan"])
        self.assertEqual(normalize_species("Pecan, Apple"), ["Apple", "Pecan"])
        self.assertEqual(normalize_species(None), [])

    def check_store(self, store):
        store.add_user(ORCID_A, "Jane", species=["Pecan"])
        self.assertEqual(store.get_active_user(ORCID_A)["species"], ["Pecan"])
        self.assertTrue(store.set_species(ORCID_A, ["Apple", "Pecan"]))
        self.assertEqual(store.list_users()[0]["species"], ["Apple", "Pecan"])
        self.assertFalse(store.set_species("0000-0002-3456-789X", ["Apple"]))

    def test_sqlite_store(self):
        self.check_store(SqliteUserStore(make_db(self)))

    def test_firestore_store(self):
        self.check_store(FirestoreUserStore(client=FakeFirestoreClient()))

    def test_sqlite_table_without_species_column_is_upgraded(self):
        db = make_db(self)
        db.execute_update("DROP TABLE users")
        db.execute_update("CREATE TABLE users (id INTEGER PRIMARY KEY, orcid_id TEXT UNIQUE, "
                          "display_name TEXT, email TEXT, role TEXT, is_active INTEGER DEFAULT 1, "
                          "created_at TEXT)")
        db.execute_update("INSERT INTO users (orcid_id, role) VALUES (?, 'user')", (ORCID_A,))
        store = SqliteUserStore(db)

        self.assertEqual(store.get_active_user(ORCID_A)["species"], [])
        self.assertTrue(store.set_species(ORCID_A, ["Apple"]))
        self.assertEqual(store.get_active_user(ORCID_A)["species"], ["Apple"])


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db(self)
        self.app = Flask(__name__)
        self.app.secret_key = "test"

    def as_user(self, role, species):
        ctx = self.app.test_request_context()
        ctx.push()
        self.addCleanup(ctx.pop)
        session["orcid_id"] = ORCID_A
        access.store_access(role, species)

    def test_admin_sees_every_species(self):
        self.as_user("admin", [])
        self.assertIsNone(access.allowed_species_ids(self.db))
        self.assertIsNone(access.check_dash_request(
            {"inputs": [entry("selected-species-store", "data", PECAN)]}, self.db))

    def test_user_species_match_scientific_or_common_name(self):
        self.as_user("user", ["malus domestica", "Unknown"])
        self.assertEqual(access.allowed_species_ids(self.db), {APPLE})

    def test_user_with_no_species_sees_none(self):
        self.as_user("user", [])
        self.assertEqual(access.allowed_species_ids(self.db), frozenset())
        self.assertIsNotNone(access.check_dash_request(
            {"inputs": [entry("selected-species-store", "data", APPLE)]}, self.db))

    def test_species_values_are_checked(self):
        self.as_user("user", ["Apple"])
        ok = {"inputs": [entry("selected-species-store", "data", APPLE)],
              "state": [entry("global-species-dropdown", "value", str(APPLE))]}
        self.assertIsNone(access.check_dash_request(ok, self.db))
        bad = {"inputs": [entry("selected-species-store", "data", APPLE)],
               "state": [entry("global-species-dropdown", "value", PECAN)]}
        self.assertIsNotNone(access.check_dash_request(bad, self.db))
        junk = {"inputs": [entry("selected-species-store", "data", "1 OR 1=1")]}
        self.assertIsNotNone(access.check_dash_request(junk, self.db))

    def test_locus_and_microhaplotype_references_are_checked(self):
        self.as_user("user", ["Apple"])
        cases = [
            entry("navigate-to-marker-store", "data", {"marker_id": "pecanChr01_200"}),
            entry("marker-detail-store", "data", "pecanChr01_200"),
            entry("marker-alignment-store", "data", {"marker_id": "pecanChr01_200"}),
            entry("navigate-to-haplotype-store", "data",
                  {"haplotype_name": "pecanChr01_200|Ref_0001"}),
            entry("overview-genome-plot", "clickData",
                  {"points": [{"customdata": ["pecanChr01_200", "Chr01", 1]}]}),
            # Wildcard inputs arrive as a nested list of entries.
            [entry({"type": "marker-list-item", "index": "pecanChr01_200"}, "n_clicks", 1)],
            [entry({"type": "view-marker-btn", "index": "pecanChr01_200"}, "n_clicks", 1)],
            [entry({"type": "haplotype-list-item", "index": "pecanChr01_200|Ref_0001"},
                   "n_clicks", 1)],
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertIsNotNone(access.check_dash_request({"inputs": [case]}, self.db))

        allowed = {"inputs": [
            entry("navigate-to-marker-store", "data", {"marker_id": "appleChr01_100"}),
            [entry({"type": "haplotype-list-item", "index": "appleChr01_100|Ref_0001"},
                   "n_clicks", 1)],
            entry("marker-detail-store", "data", "no-such-locus"),
        ]}
        self.assertIsNone(access.check_dash_request(allowed, self.db))

    def test_empty_species_is_missing_only_for_restricted_users(self):
        empty = {"inputs": [entry("selected-species-store", "data", None)]}
        unrelated = {"inputs": [entry("toggle-samples", "n_clicks", 1)]}
        self.as_user("user", ["Apple"])
        self.assertTrue(access.species_missing(empty))
        self.assertFalse(access.species_missing(unrelated))
        access.store_access("admin", [])
        self.assertFalse(access.species_missing(empty))

    def test_access_is_reread_when_stale(self):
        self.as_user("user", ["Apple"])
        store = FirestoreUserStore(client=FakeFirestoreClient())
        store.add_user(ORCID_A, species=["Pecan"])
        with patch("auth.user_store.get_user_store", return_value=store):
            self.assertTrue(access.refresh_access())
            self.assertEqual(session["user_species"], ["Apple"])  # still fresh

            session["access_checked_at"] = time.time() - access.ACCESS_REFRESH_SECONDS - 1
            self.assertTrue(access.refresh_access())
            self.assertEqual(session["user_species"], ["Pecan"])

            store.set_active(ORCID_A, False)
            session["access_checked_at"] = 0
            self.assertFalse(access.refresh_access())

    def test_bypass_sessions_are_not_refreshed(self):
        self.as_user("admin", [])
        access.store_access("admin", [], refreshable=False)
        with patch("auth.user_store.get_user_store", side_effect=AssertionError("read")):
            self.assertTrue(access.refresh_access())


class ScopedStatisticsTests(unittest.TestCase):
    def test_counts_only_the_given_species(self):
        db = make_db(self)
        everything = get_database_statistics(db)
        pecan = get_database_statistics(db, {PECAN})
        nothing = get_database_statistics(db, set())

        self.assertEqual(everything["species_count"], 2)
        self.assertEqual(pecan["species_count"], 1)
        self.assertEqual(pecan["marker_count"], 1)
        self.assertEqual(pecan["microhaplotype_count"], 1)
        self.assertEqual(pecan["sample_count"], 1)
        self.assertEqual(get_database_statistics(db, {APPLE})["sample_count"], 0)
        self.assertEqual(set(nothing.values()), {0})


class DashRequestGuardTests(unittest.TestCase):
    """The before_request hook in app.py on the real Dash server."""

    @classmethod
    def setUpClass(cls):
        import app as hapsearch_app
        cls.server = hapsearch_app.server
        cls.path = hapsearch_app.DASH_UPDATE_PATH

    def setUp(self):
        self.db = make_db(self)
        patcher = patch("database.db_manager.DatabaseManager", return_value=self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        bypass = patch("config.BYPASS_ORCID_AUTH", False)
        bypass.start()
        self.addCleanup(bypass.stop)
        self.client = self.server.test_client()

    def post(self, species_id):
        # load_global_programs in app.py: a real callback keyed on the species.
        return self.client.post(self.path, json={
            "output": "..global-programs-dropdown.options...global-programs-dropdown.value..",
            "outputs": [{"id": "global-programs-dropdown", "property": "options"},
                        {"id": "global-programs-dropdown", "property": "value"}],
            "inputs": [entry("selected-species-store", "data", species_id)],
            "changedPropIds": ["selected-species-store.data"], "state": [],
        })

    def sign_in(self, role, species):
        with self.client.session_transaction() as sess:
            sess["orcid_id"] = ORCID_A
            sess["user_role"] = role
            sess["user_species"] = species
            sess["access_checked_at"] = time.time()

    def test_signed_out_callbacks_are_refused(self):
        self.assertEqual(self.post(APPLE).status_code, 401)

    def test_other_species_are_refused(self):
        self.sign_in("user", ["Apple"])
        self.assertEqual(self.post(PECAN).status_code, 403)
        self.assertEqual(self.post(APPLE).status_code, 200)

    def test_empty_species_gets_no_update_for_restricted_users(self):
        # An empty species would make the searches cover every species.
        self.sign_in("user", ["Apple"])
        self.assertEqual(self.post(None).status_code, 204)

    def test_admin_passes(self):
        self.sign_in("admin", [])
        self.assertEqual(self.post(PECAN).status_code, 200)



def _component_ids(dependency):
    """Component ids (or pattern types) a callback reads, from _dash-dependencies."""
    for item in dependency.get("inputs", []) + dependency.get("state", []):
        comp_id = item["id"]
        if isinstance(comp_id, str) and comp_id.startswith("{"):
            comp_id = json.loads(comp_id)
        yield comp_id.get("type") if isinstance(comp_id, dict) else comp_id


class CallbackCoverageTests(unittest.TestCase):
    """Every id a callback reads must be checked or reviewed as safe.

    If this fails after adding or renaming a component: when its value names a
    species, locus or microhaplotype (or picks one, like a locus id typed into
    a box), add it to the checked sets in auth/access.py. Otherwise add it to
    access.UNCHECKED_SAFE with the reason no check is needed.
    """

    def test_every_callback_input_is_classified(self):
        import app as hapsearch_app
        response = hapsearch_app.server.test_client().get("/app/_dash-dependencies")
        self.assertEqual(response.status_code, 200)
        dependencies = response.get_json()
        self.assertGreater(len(dependencies), 30)

        read = {comp_id for dep in dependencies for comp_id in _component_ids(dep)}
        known = access.CHECKED_IDS | set(access.UNCHECKED_SAFE)

        self.assertEqual(sorted(read - known), [],
                         "callback inputs with no access decision; see this test's docstring")
        self.assertFalse(access.CHECKED_IDS & set(access.UNCHECKED_SAFE))


if __name__ == "__main__":
    unittest.main()
