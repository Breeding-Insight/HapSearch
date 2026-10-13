"""ORCID allowlist storage.

Users live in Firestore on Cloud Run (``users/{orcid_id}``, the same document
shape as HapApp and AlloMate), because the SQLite file there is read-only
inside the image. Local development and the VM keep using the SQLite
``users`` table. Both backends expose the same methods and return the same
dict shape, so the login check and CLI do not care which is used. The app
itself only reads; changes are made with scripts/manage_users.py or the
Firestore console.
"""

import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import config

try:
    from google.api_core.exceptions import Conflict as _FirestoreConflict
except ImportError:  # Firestore is optional outside Cloud Run.
    _FirestoreConflict = ()

USERS_COLLECTION = "users"
ROLES = ("admin", "user")
_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


class UserExistsError(ValueError):
    """Raised when adding an ORCID iD that is already on the allowlist."""


def normalize_orcid(orcid_id: str) -> str:
    """Return a canonical ORCID iD or raise ValueError."""
    value = (orcid_id or "").strip().upper()
    for prefix in ("HTTPS://ORCID.ORG/", "HTTP://ORCID.ORG/"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    if not _ORCID_RE.match(value):
        raise ValueError(f"'{orcid_id}' is not an ORCID iD (expected 0000-0000-0000-0000)")
    return value


def _validate_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}")
    return role


def _format_time(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _user_record(values: Dict[str, Any], orcid_id: str) -> Dict[str, Any]:
    return {
        "orcid_id": values.get("orcid_id") or orcid_id,
        "display_name": values.get("display_name"),
        "email": values.get("email"),
        "role": values.get("role") or "user",
        "is_active": bool(values.get("is_active", False)),
        "created_at": _format_time(values.get("created_at")),
    }


class SqliteUserStore:
    """Allowlist in the SQLite ``users`` table."""

    backend = "sqlite"

    def __init__(self, db=None):
        if db is None:
            from database.db_manager import DatabaseManager
            db = DatabaseManager()
        self.db = db

    def _ensure_table(self) -> None:
        self.db.execute_update("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                orcid_id TEXT NOT NULL UNIQUE,
                display_name TEXT,
                email TEXT,
                role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def assert_ready(self) -> None:
        self.db.execute_query("SELECT 1 FROM users LIMIT 1")

    def get_active_user(self, orcid_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.execute_query(
            "SELECT * FROM users WHERE orcid_id = ? AND is_active = 1", (orcid_id,)
        )
        return _user_record(rows[0], orcid_id) if rows else None

    def list_users(self) -> List[Dict[str, Any]]:
        if not self.db.table_exists("users"):
            return []
        rows = self.db.execute_query("SELECT * FROM users ORDER BY created_at, id")
        return [_user_record(row, row["orcid_id"]) for row in rows]

    def add_user(self, orcid_id: str, display_name: str = None, email: str = None,
                 role: str = "user") -> Dict[str, Any]:
        orcid_id = normalize_orcid(orcid_id)
        _validate_role(role)
        self._ensure_table()
        if self.db.execute_query("SELECT 1 FROM users WHERE orcid_id = ?", (orcid_id,)):
            raise UserExistsError(f"User with ORCID {orcid_id} already exists.")
        self.db.execute_update(
            "INSERT INTO users (orcid_id, display_name, email, role) VALUES (?, ?, ?, ?)",
            (orcid_id, display_name or None, email or None, role),
        )
        return self.get_active_user(orcid_id)

    def set_active(self, orcid_id: str, is_active: bool) -> bool:
        return self.db.execute_update(
            "UPDATE users SET is_active = ? WHERE orcid_id = ?", (1 if is_active else 0, orcid_id)
        ) > 0

    def set_role(self, orcid_id: str, role: str) -> bool:
        return self.db.execute_update(
            "UPDATE users SET role = ? WHERE orcid_id = ?", (_validate_role(role), orcid_id)
        ) > 0

    def remove_user(self, orcid_id: str) -> bool:
        return self.db.execute_update("DELETE FROM users WHERE orcid_id = ?", (orcid_id,)) > 0


class FirestoreUserStore:
    """Allowlist in Firestore, one ``users/{orcid_id}`` document per person.

    Uses Application Default Credentials, i.e. the Cloud Run service identity;
    no key file is needed.
    """

    backend = "firestore"

    def __init__(self, client=None):
        if client is None:
            try:
                from google.cloud import firestore
            except ImportError as exc:
                raise ImportError(
                    "google-cloud-firestore is required when HAPSEARCH_USER_STORE=firestore"
                ) from exc
            client = firestore.Client(
                project=config.GOOGLE_CLOUD_PROJECT or None,
                database=config.FIRESTORE_DATABASE,
            )
        self.client = client

    def _doc(self, orcid_id: str):
        return self.client.collection(USERS_COLLECTION).document(orcid_id)

    def _get(self, orcid_id: str) -> Optional[Dict[str, Any]]:
        snapshot = self._doc(orcid_id).get()
        return (snapshot.to_dict() or {}) if snapshot.exists else None

    def assert_ready(self) -> None:
        """Perform a minimal authenticated read without requiring seeded data."""
        self.client.collection(USERS_COLLECTION).limit(1).get()

    def get_active_user(self, orcid_id: str) -> Optional[Dict[str, Any]]:
        values = self._get(orcid_id)
        if not values or not values.get("is_active", False):
            return None
        return _user_record(values, orcid_id)

    def list_users(self) -> List[Dict[str, Any]]:
        users = [
            _user_record(snapshot.to_dict() or {}, snapshot.id)
            for snapshot in self.client.collection(USERS_COLLECTION).stream()
        ]
        return sorted(users, key=lambda user: (user["created_at"] or "", user["orcid_id"]))

    def add_user(self, orcid_id: str, display_name: str = None, email: str = None,
                 role: str = "user", *, is_active: bool = True,
                 created_at: Optional[datetime] = None) -> Dict[str, Any]:
        orcid_id = normalize_orcid(orcid_id)
        _validate_role(role)
        values = {
            "orcid_id": orcid_id,
            "display_name": display_name or None,
            "email": email or None,
            "role": role,
            "is_active": bool(is_active),
            "created_at": created_at or datetime.now(timezone.utc),
        }
        try:
            # create() fails if the document exists, so adding someone twice
            # cannot overwrite their existing record.
            self._doc(orcid_id).create(values)
        except _FirestoreConflict as exc:
            raise UserExistsError(f"User with ORCID {orcid_id} already exists.") from exc
        return _user_record(values, orcid_id)

    def _update(self, orcid_id: str, values: Dict[str, Any]) -> bool:
        if self._get(orcid_id) is None:
            return False
        self._doc(orcid_id).update(values)
        return True

    def set_active(self, orcid_id: str, is_active: bool) -> bool:
        return self._update(orcid_id, {"is_active": bool(is_active)})

    def set_role(self, orcid_id: str, role: str) -> bool:
        return self._update(orcid_id, {"role": _validate_role(role)})

    def remove_user(self, orcid_id: str) -> bool:
        if self._get(orcid_id) is None:
            return False
        self._doc(orcid_id).delete()
        return True


_store = None
_store_lock = threading.Lock()


def create_user_store(backend: Optional[str] = None):
    """Build a store for the given backend (defaults to config.USER_STORE)."""
    backend = (backend or config.USER_STORE).strip().lower()
    if backend == "firestore":
        return FirestoreUserStore()
    if backend == "sqlite":
        return SqliteUserStore()
    raise ValueError("HAPSEARCH_USER_STORE must be 'sqlite' or 'firestore'")


def get_user_store():
    """Return the process-wide store for the configured backend."""
    global _store
    with _store_lock:
        if _store is None:
            _store = create_user_store()
        return _store
