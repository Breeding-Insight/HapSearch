#!/usr/bin/env python3
"""Initialize the HaploSearch SQLite database."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from database.db_manager import DatabaseManager, SCHEMA_PATH


def init_database(schema_file: str = None, force: bool = False,
                  db_path: str = None):
    """Create the SQLite schema, optionally replacing an existing database file."""
    schema_file = schema_file or SCHEMA_PATH
    db_path = db_path or config.SQLITE_DB_PATH

    if not os.path.exists(schema_file):
        print(f"Error: Schema file not found: {schema_file}")
        return False

    if force and os.path.exists(db_path):
        print(f"Force mode: removing existing database {db_path}")
        for suffix in ('', '-wal', '-shm', '-journal'):
            if os.path.exists(db_path + suffix):
                os.remove(db_path + suffix)

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    print(f"Initializing SQLite database at {db_path}...")

    try:
        db = DatabaseManager(db_path=db_path, read_only=False)
        db.ensure_schema(schema_file)
        tables = db.execute_query(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    except Exception as e:
        print(f"Error creating schema: {e}")
        return False

    print("Schema created successfully!")
    print(f"\nDatabase has {len(tables)} tables:")
    for table in tables:
        print(f"  - {table['name']}")
    return True


def add_sample_data(db_path: str = None):
    """Add sample data for testing."""
    db = DatabaseManager(db_path=db_path, read_only=False)
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO species (name, common_name, description)
                VALUES (?, ?, ?)
            """, ('Homo sapiens', 'Human', 'Sample human data'))
            species_id = cursor.lastrowid

            chromosome_names = [f"Chr{i}" for i in range(1, 23)] + ['ChrX', 'ChrY']
            cursor.executemany("""
                INSERT INTO chromosomes (species_id, chromosome_name)
                VALUES (?, ?)
            """, [(species_id, name) for name in chromosome_names])

            cursor.execute("""
                INSERT INTO projects (project_code, project_name, pi_name, pi_email,
                                    pi_institution, pi_department, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ('PROJ001', 'Sample Project', 'Dr. Jane Smith',
                  'jane.smith@university.edu', 'University of Example',
                  'Department of Biology', 'Sample project for testing'))
    except Exception as e:
        print(f"Error adding sample data: {e}")
        return False

    print("\nSample data added successfully!")
    return True


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Initialize HaploSearch database')
    parser.add_argument('--schema', help='Path to schema SQL file')
    parser.add_argument('--force', action='store_true',
                        help='Delete the existing database file before creating the schema')
    parser.add_argument('--sample-data', action='store_true',
                        help='Add sample data for testing')
    parser.add_argument('--db-path',
                        help='SQLite database path (overrides SQLITE_DB_PATH)')
    parser.add_argument('--optimize', action='store_true',
                        help='Refresh planner statistics and compact an existing '
                             'database (run after imports, before building the image)')

    args = parser.parse_args()

    if args.optimize:
        db = DatabaseManager(db_path=args.db_path, read_only=False)
        db.optimize(vacuum=True)
        size_mb = os.path.getsize(db.db_path) / 1024 / 1024
        print(f"Optimized {db.db_path} ({size_mb:.1f} MB)")
        sys.exit(0)

    success = init_database(
        schema_file=args.schema,
        force=args.force,
        db_path=args.db_path
    )

    if success and args.sample_data:
        success = add_sample_data(args.db_path)

    sys.exit(0 if success else 1)
