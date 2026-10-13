import os
import tempfile
import unittest
from unittest.mock import patch

from google.api_core.exceptions import AlreadyExists, NotFound

from auth import session as auth_session
from auth.user_store import (
    FirestoreUserStore,
    SqliteUserStore,
    UserExistsError,
    normalize_orcid,
)
from database.db_manager import DatabaseManager


class FakeSnapshot:
    def __init__(self, doc_id, values):
        self.id = doc_id
        self.exists = values is not None
        self._values = values

    def to_dict(self):
        return dict(self._values) if self._values is not None else None


class FakeDocument:
    def __init__(self, docs, doc_id):
        self._docs = docs
        self.id = doc_id

    def get(self):
        return FakeSnapshot(self.id, self._docs.get(self.id))

    def create(self, values):
        if self.id in self._docs:
            raise AlreadyExists("document exists")
        self._docs[self.id] = dict(values)

    def update(self, values):
        if self.id not in self._docs:
            raise NotFound("no document")
        self._docs[self.id].update(values)

    def delete(self):
        self._docs.pop(self.id, None)


class FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def document(self, doc_id):
        return FakeDocument(self._docs, doc_id)

    def stream(self):
        return [FakeSnapshot(doc_id, values) for doc_id, values in self._docs.items()]

    def limit(self, _count):
        return self

    def get(self):
        return self.stream()


class FakeFirestoreClient:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        return FakeCollection(self.collections.setdefault(name, {}))


ORCID_A = "0000-0001-2345-6789"
ORCID_B = "0000-0002-3456-789X"


class UserStoreContract:
    """Behaviour both backends must share."""

    def make_store(self):
        raise NotImplementedError

    def setUp(self):
        self.store = self.make_store()

    def test_add_and_look_up_active_user(self):
        self.store.add_user(ORCID_A, "Jane Doe", "jane@example.org", "admin")

        user = self.store.get_active_user(ORCID_A)

        self.assertEqual(user["display_name"], "Jane Doe")
        self.assertEqual(user["role"], "admin")
        self.assertTrue(user["is_active"])
        self.assertIsNone(self.store.get_active_user(ORCID_B))

    def test_duplicate_add_is_rejected(self):
        self.store.add_user(ORCID_A)
        with self.assertRaises(UserExistsError):
            self.store.add_user(ORCID_A)

    def test_invalid_orcid_and_role_are_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add_user("not-an-orcid")
        with self.assertRaises(ValueError):
            self.store.add_user(ORCID_A, role="owner")

    def test_deactivated_user_cannot_sign_in(self):
        self.store.add_user(ORCID_A)

        self.assertTrue(self.store.set_active(ORCID_A, False))
        self.assertIsNone(self.store.get_active_user(ORCID_A))
        self.assertTrue(self.store.set_active(ORCID_A, True))
        self.assertIsNotNone(self.store.get_active_user(ORCID_A))

    def test_role_changes(self):
        self.store.add_user(ORCID_A)

        self.assertTrue(self.store.set_role(ORCID_A, "admin"))
        self.assertEqual(self.store.get_active_user(ORCID_A)["role"], "admin")

    def test_list_users(self):
        self.store.add_user(ORCID_A, "Jane Doe")
        self.store.add_user(ORCID_B, "Lab Member")

        users = {user["orcid_id"]: user for user in self.store.list_users()}

        self.assertEqual(set(users), {ORCID_A, ORCID_B})
        self.assertEqual(users[ORCID_B]["display_name"], "Lab Member")
        self.assertIsNotNone(users[ORCID_A]["created_at"])

    def test_missing_users_report_not_found(self):
        self.assertFalse(self.store.set_active(ORCID_A, False))
        self.assertFalse(self.store.set_role(ORCID_A, "admin"))
        self.assertFalse(self.store.remove_user(ORCID_A))

    def test_remove_user(self):
        self.store.add_user(ORCID_A)

        self.assertTrue(self.store.remove_user(ORCID_A))
        self.assertEqual(self.store.list_users(), [])


class SqliteUserStoreTests(UserStoreContract, unittest.TestCase):
    def make_store(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db = DatabaseManager(db_path=os.path.join(temp_dir.name, "users.db"), read_only=False)
        db.ensure_schema()
        return SqliteUserStore(db)


class FirestoreUserStoreTests(UserStoreContract, unittest.TestCase):
    def make_store(self):
        self.client = FakeFirestoreClient()
        return FirestoreUserStore(client=self.client)

    def test_documents_use_the_shared_bi_shape(self):
        self.store.add_user(ORCID_A, "Jane Doe", role="admin")

        document = self.client.collections["users"][ORCID_A]

        self.assertEqual(document["orcid_id"], ORCID_A)
        self.assertIs(document["is_active"], True)
        self.assertEqual(document["role"], "admin")


class OrcidNormalizationTests(unittest.TestCase):
    def test_accepts_urls_and_lowercase_checksum(self):
        self.assertEqual(normalize_orcid(" https://orcid.org/0000-0002-3456-789x "), ORCID_B)


class SessionLookupTests(unittest.TestCase):
    def test_lookup_user_uses_store_and_hides_errors(self):
        store = FirestoreUserStore(client=FakeFirestoreClient())
        store.add_user(ORCID_A, "Jane Doe")
        with patch.object(auth_session, "get_user_store", return_value=store):
            self.assertEqual(auth_session.lookup_user(ORCID_A)["display_name"], "Jane Doe")
            self.assertIsNone(auth_session.lookup_user(ORCID_B))

        class BrokenStore:
            def get_active_user(self, _orcid):
                raise RuntimeError("Firestore unavailable")

        with patch.object(auth_session, "get_user_store", return_value=BrokenStore()):
            self.assertIsNone(auth_session.lookup_user(ORCID_A))


if __name__ == "__main__":
    unittest.main()
