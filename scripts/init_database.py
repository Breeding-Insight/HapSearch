#!/usr/bin/env python3
"""Initialize the HaploSearch Microsoft SQL Server database."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False


def init_database(schema_file: str = None, force: bool = False,
                  connection_string: str = None):
    """Initialize the configured Microsoft SQL Server database."""
    if not PYODBC_AVAILABLE:
        print("Error: pyodbc is required for Microsoft SQL Server connections.")
        print("Install it with: pip install pyodbc")
        return False

    if schema_file is None:
        schema_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'schema_mssql.sql'
        )

    connection_string = connection_string or config.DATABASE_CONNECTION_STRING

    if not os.path.exists(schema_file):
        print(f"Error: Schema file not found: {schema_file}")
        return False

    with open(schema_file, 'r') as f:
        schema_sql = f.read()

    print("Connecting to Microsoft SQL Server database...")
    print(f"Connection string: {connection_string.split('PWD=')[0]}PWD=***")

    conn = None
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()

        if force:
            print("Force mode: dropping existing tables...")
            tables = [
                'microhaplotype_presence_summary', 'presence_artifacts',
                # Legacy presence edge tables from the rowstore design. They are
                # no longer created by schema_mssql.sql, but stale dev DBs may
                # still have FKs from these tables to microhaplotypes/projects/samples.
                'allele_project_presence', 'allele_sample_presence',
                'microhaplotype_samples',
                'variants', 'botloci', 'microhaplotypes', 'samples',
                'project_contacts', 'projects', 'contacts', 'users',
                'markers', 'chromosomes', 'species'
            ]
            for table in tables:
                cursor.execute(f"DROP TABLE IF EXISTS [{table}]")
            conn.commit()

        print("Creating schema...")
        statements = [s.strip() for s in schema_sql.split('GO') if s.strip()]
        for statement in statements:
            cursor.execute(statement)

        conn.commit()
        print("Schema created successfully!")

        cursor.execute("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """)
        tables = cursor.fetchall()
        print(f"\nCreated {len(tables)} tables:")
        for table in tables:
            print(f"  - {table[0]}")

        return True

    except pyodbc.Error as e:
        print(f"Error creating schema: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def add_sample_data():
    """Add sample data for testing."""
    if not PYODBC_AVAILABLE:
        print("Error: pyodbc is required for Microsoft SQL Server connections.")
        return False

    conn = None
    try:
        conn = pyodbc.connect(config.DATABASE_CONNECTION_STRING)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO species (name, common_name, description)
            VALUES (?, ?, ?)
        """, ('Homo sapiens', 'Human', 'Sample human data'))
        cursor.execute("SELECT SCOPE_IDENTITY()")
        species_id = cursor.fetchone()[0]

        for i in range(1, 23):
            cursor.execute("""
                INSERT INTO chromosomes (species_id, chromosome_name)
                VALUES (?, ?)
            """, (species_id, f"Chr{i}"))

        cursor.execute("""
            INSERT INTO chromosomes (species_id, chromosome_name)
            VALUES (?, 'ChrX')
        """, (species_id,))
        cursor.execute("""
            INSERT INTO chromosomes (species_id, chromosome_name)
            VALUES (?, 'ChrY')
        """, (species_id,))

        cursor.execute("""
            INSERT INTO projects (project_code, project_name, pi_name, pi_email,
                                pi_institution, pi_department, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ('PROJ001', 'Sample Project', 'Dr. Jane Smith',
              'jane.smith@university.edu', 'University of Example',
              'Department of Biology', 'Sample project for testing'))

        conn.commit()
        print("\nSample data added successfully!")
        return True

    except pyodbc.Error as e:
        print(f"Error adding sample data: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Initialize HaploSearch database')
    parser.add_argument('--schema', help='Path to schema SQL file')
    parser.add_argument('--force', action='store_true',
                        help='Drop existing tables before creating schema')
    parser.add_argument('--sample-data', action='store_true',
                        help='Add sample data for testing')
    parser.add_argument('--connection-string',
                        help='Microsoft SQL Server connection string (overrides config)')

    args = parser.parse_args()

    success = init_database(
        schema_file=args.schema,
        force=args.force,
        connection_string=args.connection_string
    )

    if success and args.sample_data:
        success = add_sample_data()

    sys.exit(0 if success else 1)
