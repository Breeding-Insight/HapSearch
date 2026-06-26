import unittest

from database.queries import get_species_snapshot


class FakeSpeciesSnapshotDb:
    def __init__(self):
        self.rare_query = None

    def execute_query(self, query, params=()):
        if "FROM species" in query:
            return [{"name": "Malus domestica", "common_name": "Apple"}]
        if "COUNT(DISTINCT mk.id) AS marker_count" in query:
            return [{"marker_count": 4, "microhaplotype_count": 10}]
        if "COUNT(*) AS sample_count" in query:
            return [{"sample_count": 6}]
        if "FROM projects p" in query:
            return [
                {
                    "id": 1,
                    "project_code": "P1",
                    "project_name": "Project One",
                    "pi_name": "PI One",
                }
            ]
        if "FROM microhaplotype_presence_summary" in query:
            return [{"project_count": 1}]
        if "COUNT(*) AS rare_count" in query:
            self.rare_query = query
            return [{"rare_count": 3}]
        return []


class SpeciesSnapshotTests(unittest.TestCase):
    def test_rare_microhaplotypes_count_only_singletons(self):
        db = FakeSpeciesSnapshotDb()

        snapshot = get_species_snapshot(db, 1)

        self.assertEqual(snapshot["rare_microhaplotypes"], 3)
        self.assertNotIn("rare_alleles", snapshot)
        self.assertIn("m.sample_count = 1", db.rare_query)
        self.assertNotIn("m.sample_count <= 1", db.rare_query)


if __name__ == "__main__":
    unittest.main()
