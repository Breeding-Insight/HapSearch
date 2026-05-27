import unittest

from pages.collaborator_rows import build_collaborator_rows_from_contacts


class CollaboratorRowsTests(unittest.TestCase):
    def test_returns_empty_when_no_contacts(self):
        self.assertEqual(build_collaborator_rows_from_contacts(None), [])
        self.assertEqual(build_collaborator_rows_from_contacts([]), [])

    def test_builds_rows_from_contacts_only(self):
        contacts = [
            {
                "project_id": 1,
                "full_name": "Debby Samac",
                "email": "debby.samac@usda.gov",
                "institution": "USDA ARS",
                "location": "ARS St. Paul MN - PSR",
            }
        ]
        rows = build_collaborator_rows_from_contacts(contacts)
        self.assertEqual(
            rows,
            [
                {
                    "Name": "Debby Samac",
                    "Institution": "USDA ARS",
                    "Location": "ARS St. Paul MN - PSR",
                    "Email": "debby.samac@usda.gov",
                }
            ],
        )

    def test_deduplicates_repeated_contacts(self):
        contacts = [
            {
                "project_id": 1,
                "full_name": "Debby Samac",
                "email": "debby.samac@usda.gov",
                "institution": "USDA ARS",
                "location": "ARS St. Paul MN - PSR",
            },
            {
                "project_id": 2,
                "full_name": "Debby Samac",
                "email": "debby.samac@usda.gov",
                "institution": "USDA ARS",
                "location": "ARS St. Paul MN - PSR",
            },
        ]
        rows = build_collaborator_rows_from_contacts(contacts)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Name"], "Debby Samac")

    def test_sorts_alphabetically_then_pushes_missing_to_bottom(self):
        contacts = [
            {
                "full_name": "Aaron Zeta",
                "email": "aaron@example.com",
                "institution": "Inst 1",
                "location": "MN",
            },
            {
                "full_name": "Brenda Alpha",
                "email": "brenda@example.com",
                "institution": "Inst 2",
                "location": "CA",
            },
            {
                "full_name": "Adam Missing Email",
                "email": "",
                "institution": "Inst 3",
                "location": "TX",
            },
            {
                "full_name": "Abel Missing Location",
                "email": "abel@example.com",
                "institution": "Inst 4",
                "location": "",
            },
        ]

        rows = build_collaborator_rows_from_contacts(contacts)
        self.assertEqual(
            [row["Name"] for row in rows],
            [
                "Aaron Zeta",
                "Brenda Alpha",
                "Abel Missing Location",
                "Adam Missing Email",
            ],
        )


if __name__ == "__main__":
    unittest.main()
