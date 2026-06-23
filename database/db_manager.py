"""Database manager for HaploSearch."""

import time
import logging
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
import config

logger = logging.getLogger(__name__)

try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False


class DatabaseManager:
    """Manages Microsoft SQL Server connections and operations."""

    _CONNECT_RETRIES = 3
    _CONNECT_BACKOFF_BASE = 1.0  # seconds; doubles each retry

    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or config.DATABASE_CONNECTION_STRING
        self._shared_conn = None

        if not PYODBC_AVAILABLE:
            raise ImportError(
                "pyodbc is required for Microsoft SQL Server connections. "
                "Install it with: pip install pyodbc"
            )

    def _open_connection(self):
        """Open a new database connection with retry logic for transient failures."""
        last_err = None
        for attempt in range(1, self._CONNECT_RETRIES + 1):
            try:
                return pyodbc.connect(self.connection_string)
            except Exception as exc:
                last_err = exc
                if attempt < self._CONNECT_RETRIES:
                    wait = self._CONNECT_BACKOFF_BASE * (2 ** (attempt - 1))
                    logger.warning(
                        "SQL Server connect attempt %d/%d failed (%s); retrying in %.1fs",
                        attempt, self._CONNECT_RETRIES, exc, wait,
                    )
                    time.sleep(wait)
        raise last_err  # type: ignore[misc]

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
        query = self._normalize_query_for_mssql(query)
        
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

    def get_last_insert_id(self) -> int:
        """Get the last inserted row ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SCOPE_IDENTITY()")
            result = cursor.fetchone()
            return result[0] if result else None

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database"""
        query = f"""
            SELECT COUNT(*) as count
            FROM sys.objects
            WHERE object_id = OBJECT_ID(N'[dbo].[{table_name}]') AND type in (N'U')
        """
        results = self.execute_query(query)
        return results[0]['count'] > 0 if results else False

    def get_table_row_count(self, table_name: str) -> int:
        """Get the number of rows in a table"""
        query = f"SELECT COUNT(*) as count FROM [{table_name}]"
        result = self.execute_query(query)
        return result[0]['count'] if result else 0

    def _normalize_query_for_mssql(self, query: str) -> str:
        """Normalize legacy query helpers to Microsoft SQL Server syntax."""
        import re
        
        # 1. Replace LIMIT in EXISTS subqueries with TOP
        pattern = r'(EXISTS\s*\([^)]*?)LIMIT\s+1'
        query = re.sub(pattern, r'\1TOP 1', query, flags=re.IGNORECASE | re.DOTALL)
        
        # 2. Replace LIMIT...OFFSET at end of query with OFFSET...FETCH NEXT
        # Pattern: LIMIT n OFFSET m or LIMIT n (at end of query)
        # SQL Server syntax: OFFSET m ROWS FETCH NEXT n ROWS ONLY
        limit_offset_pattern = r'LIMIT\s+(\d+)\s+OFFSET\s+(\d+)(?=\s*$|\s*;|\s*$)'
        def replace_limit_offset(match):
            limit = match.group(1)
            offset = match.group(2)
            return f'OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY'
        query = re.sub(limit_offset_pattern, replace_limit_offset, query, flags=re.IGNORECASE | re.MULTILINE)
        
        # 3. Replace standalone LIMIT at end (without OFFSET)
        # This is trickier - we'll handle it if OFFSET is 0
        limit_only_pattern = r'LIMIT\s+(\d+)(?=\s*$|\s*;|\s*$)'
        def replace_limit_only(match):
            limit = match.group(1)
            return f'OFFSET 0 ROWS FETCH NEXT {limit} ROWS ONLY'
        # Only replace if not already converted by previous pattern
        if 'FETCH NEXT' not in query:
            query = re.sub(limit_only_pattern, replace_limit_only, query, flags=re.IGNORECASE | re.MULTILINE)
        
        # 4. Replace INSTR with CHARINDEX
        # INSTR(string, substring) -> CHARINDEX(substring, string)
        #
        # First handle the nested pattern used by sequence search:
        #   INSTR(UPPER(expr), UPPER(?))  ->  CHARINDEX(UPPER(?), UPPER(expr))
        instr_upper_pattern = (
            r'INSTR\s*\(\s*UPPER\s*\(\s*([^)]+?)\s*\)\s*,\s*'
            r'UPPER\s*\(\s*(\?)\s*\)\s*\)'
        )
        query = re.sub(
            instr_upper_pattern,
            r'CHARINDEX(UPPER(\2), UPPER(\1))',
            query,
            flags=re.IGNORECASE
        )

        # Fallback for simpler INSTR(a, b) calls without nested function args.
        instr_simple_pattern = r'INSTR\s*\(\s*([^,()]+)\s*,\s*([^,()]+)\s*\)'
        def replace_instr_simple(match):
            string_expr = match.group(1).strip()
            substring_expr = match.group(2).strip()
            return f'CHARINDEX({substring_expr}, {string_expr})'
        query = re.sub(instr_simple_pattern, replace_instr_simple, query, flags=re.IGNORECASE)
        
        return query


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
        cursor.execute("SELECT SCOPE_IDENTITY()")
        return cursor.fetchone()[0]


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
        cursor.execute("SELECT SCOPE_IDENTITY()")
        return cursor.fetchone()[0]


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
        cursor.execute("SELECT SCOPE_IDENTITY()")
        return cursor.fetchone()[0]


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
                CASE
                    WHEN ps.present_count IS NOT NULL THEN ps.present_count
                    ELSE ISNULL(mc.ms_present_samples, 0)
                END AS present_samples
            FROM microhaplotypes m
            JOIN markers mk ON mk.id = m.marker_id
            JOIN chromosomes c ON c.id = mk.chromosome_id
            LEFT JOIN microhaplotype_presence_summary ps
              ON ps.microhaplotype_id = m.id
             AND ps.species_id = c.species_id
             AND ps.entity_type = 'sample'
            OUTER APPLY (
                SELECT COUNT(DISTINCT s.id) AS ms_present_samples
                FROM microhaplotype_samples ms
                JOIN samples s ON s.id = ms.sample_id
                WHERE ms.microhaplotype_id = m.id
                  AND s.species_id = c.species_id
            ) mc
        )
        UPDATE m
        SET
            m.sample_count = pm.present_samples,
            m.frequency = CASE
                WHEN ISNULL(st.total_samples, 0) > 0
                    THEN CAST(pm.present_samples AS FLOAT) / CAST(st.total_samples AS FLOAT)
                ELSE 0.0
            END
        FROM microhaplotypes m
        JOIN per_microhap pm ON pm.microhaplotype_id = m.id
        LEFT JOIN species_totals st ON st.species_id = pm.species_id
    """

    db.execute_update(query)
