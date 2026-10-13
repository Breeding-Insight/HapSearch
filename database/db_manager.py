"""Database manager for HaploSearch."""

import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
import config

logger = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'schema_sqlite.sql',
)


class DatabaseManager:
    """Manages SQLite connections and operations."""

    def __init__(self, db_path: str = None, read_only: bool = None):
        self.db_path = db_path or config.SQLITE_DB_PATH
        self.read_only = config.SQLITE_READ_ONLY if read_only is None else read_only
        self._shared_conn = None

    def _open_connection(self):
        """Open a new SQLite connection.

        Read-only mode opens the file as immutable: SQLite skips locking and
        change detection, which is safe because the file baked into the image
        never changes while the instance runs.
        """
        if self.read_only:
            if not os.path.exists(self.db_path):
                raise FileNotFoundError(f"SQLite database not found: {self.db_path}")
            uri = f"file:{os.path.abspath(self.db_path)}?mode=ro&immutable=1"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def shared_connection(self):
        """Reuse a single connection for all queries inside this block.

        Usage::

            db = DatabaseManager()
            with db.shared_connection():
                rows1 = db.execute_query(q1)
                rows2 = db.execute_query(q2)   # same underlying connection
        """
        if self._shared_conn is not None:
            yield self._shared_conn
            return

        conn = self._open_connection()
        self._shared_conn = conn
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self._shared_conn = None
            conn.close()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections.

        If called inside a ``shared_connection()`` block the existing
        connection is reused (no commit/rollback/close; the outer block
        owns the lifecycle).  Otherwise a fresh connection is created and
        closed when the block exits.
        """
        if self._shared_conn is not None:
            yield self._shared_conn
            return

        conn = self._open_connection()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results as list of dicts"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)

            columns = [column[0] for column in cursor.description]

            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results

    def execute_update(self, query: str, params: tuple = ()) -> int:
        """Execute an INSERT/UPDATE/DELETE query and return affected rows"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.rowcount

    def execute_many(self, query: str, params_list: List[tuple]) -> int:
        """Execute multiple INSERT/UPDATE queries"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            return cursor.rowcount

    def ensure_schema(self, schema_file: Optional[str] = None) -> None:
        """Create any missing tables and indexes from the SQLite schema file."""
        with open(schema_file or SCHEMA_PATH, 'r', encoding='utf-8') as handle:
            schema_sql = handle.read()
        with self.get_connection() as conn:
            conn.executescript(schema_sql)

    def optimize(self, vacuum: bool = False) -> None:
        """Refresh query-planner statistics, optionally compacting the file.

        SQLite picks join orders from ANALYZE statistics; without them the
        artifact-backed ID filters fall back to scanning every marker.
        """
        with self.get_connection() as conn:
            conn.execute("ANALYZE")
        if vacuum:
            conn = self._open_connection()
            try:
                conn.execute("VACUUM")
            finally:
                conn.close()

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database"""
        results = self.execute_query(
            "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        return results[0]['count'] > 0 if results else False

    def get_table_row_count(self, table_name: str) -> int:
        """Get the number of rows in a table"""
        query = f'SELECT COUNT(*) as count FROM "{table_name}"'
        result = self.execute_query(query)
        return result[0]['count'] if result else 0


# Helper functions for common database operations

def get_or_create_species(db: DatabaseManager, name: str, common_name: str = None,
                          description: str = None) -> int:
    """Get species ID or create if doesn't exist"""
    # Check if exists
    query = "SELECT id FROM species WHERE name = ?"
    result = db.execute_query(query, (name,))

    if result:
        return result[0]['id']

    # Create new species
    query = """
        INSERT INTO species (name, common_name, description)
        VALUES (?, ?, ?)
    """
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (name, common_name, description))
        return cursor.lastrowid


def get_or_create_chromosome(db: DatabaseManager, species_id: int,
                             chromosome_name: str, length: int = None) -> int:
    """Get chromosome ID or create if doesn't exist"""
    # Check if exists
    query = "SELECT id FROM chromosomes WHERE species_id = ? AND chromosome_name = ?"
    result = db.execute_query(query, (species_id, chromosome_name))

    if result:
        return result[0]['id']

    # Create new chromosome
    query = """
        INSERT INTO chromosomes (species_id, chromosome_name, length)
        VALUES (?, ?, ?)
    """
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (species_id, chromosome_name, length))
        return cursor.lastrowid


def get_or_create_marker(db: DatabaseManager, marker_id: str, chromosome_id: int,
                        position_start: int, position_end: int,
                        marker_type: str = None, description: str = None) -> int:
    """Get marker ID or create if doesn't exist"""
    # Check if exists
    query = "SELECT id FROM markers WHERE marker_id = ?"
    result = db.execute_query(query, (marker_id,))

    if result:
        return result[0]['id']

    # Create new marker
    query = """
        INSERT INTO markers (marker_id, chromosome_id, position_start,
                           position_end, marker_type, description)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (marker_id, chromosome_id, position_start,
                              position_end, marker_type, description))
        return cursor.lastrowid


def update_chromosome_counts(db: DatabaseManager):
    """Update microhaplotype counts for all chromosomes"""
    query = """
        UPDATE chromosomes
        SET microhaplotype_count = (
            SELECT COUNT(DISTINCT m.id)
            FROM microhaplotypes m
            JOIN markers mk ON m.marker_id = mk.id
            WHERE mk.chromosome_id = chromosomes.id
        )
    """
    db.execute_update(query)


def update_haplotype_frequencies(db: DatabaseManager):
    """Calculate and update microhaplotype frequencies.

    Definition (matches Haplotype Details UI):
      frequency = (# samples containing haplotype) / (total samples for that haplotype's species)

    Notes:
    - Species for a microhaplotype is derived via markers -> chromosomes -> species.
    - Presence/absence imports maintain microhaplotype_presence_summary.
    - The older microhaplotype_samples table is still used by scripts/import_samples.py.
    """
    query = """
        WITH species_totals AS (
            SELECT s.species_id, COUNT(*) AS total_samples
            FROM samples s
            GROUP BY s.species_id
        ),
        per_microhap AS (
            SELECT
                m.id AS microhaplotype_id,
                c.species_id,
                COALESCE(
                    ps.present_count,
                    (
                        SELECT COUNT(DISTINCT s.id)
                        FROM microhaplotype_samples ms
                        JOIN samples s ON s.id = ms.sample_id
                        WHERE ms.microhaplotype_id = m.id
                          AND s.species_id = c.species_id
                    )
                ) AS present_samples
            FROM microhaplotypes m
            JOIN markers mk ON mk.id = m.marker_id
            JOIN chromosomes c ON c.id = mk.chromosome_id
            LEFT JOIN microhaplotype_presence_summary ps
              ON ps.microhaplotype_id = m.id
             AND ps.species_id = c.species_id
             AND ps.entity_type = 'sample'
        )
        UPDATE microhaplotypes
        SET
            sample_count = pm.present_samples,
            frequency = CASE
                WHEN COALESCE(st.total_samples, 0) > 0
                    THEN CAST(pm.present_samples AS REAL) / st.total_samples
                ELSE 0.0
            END
        FROM per_microhap pm
        LEFT JOIN species_totals st ON st.species_id = pm.species_id
        WHERE pm.microhaplotype_id = microhaplotypes.id
    """

    db.execute_update(query)
