#!/usr/bin/env python3
"""CLI tool for managing Haplosearch users.

Usage:
    python scripts/manage_users.py add --orcid 0000-0001-2345-6789 --name "Jane Doe" --role admin
    python scripts/manage_users.py add --orcid 0000-0002-3456-7890 --name "Lab Member"
    python scripts/manage_users.py list
    python scripts/manage_users.py deactivate --orcid 0000-0002-3456-7890
    python scripts/manage_users.py activate --orcid 0000-0002-3456-7890
    python scripts/manage_users.py set-role --orcid 0000-0002-3456-7890 --role admin
    python scripts/manage_users.py remove --orcid 0000-0002-3456-7890
"""

import argparse
import sys
import os

# Ensure project root is on the path so we can import config / database
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager  # noqa: E402


def _ensure_users_table(db: DatabaseManager):
    """Create the users table if it doesn't exist yet."""
    if not db.table_exists('users'):
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE users (
                    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
                    orcid_id NVARCHAR(255) NOT NULL UNIQUE,
                    display_name NVARCHAR(255),
                    email NVARCHAR(255),
                    role NVARCHAR(10) NOT NULL DEFAULT 'user'
                        CHECK (role IN ('admin', 'user')),
                    is_active INT DEFAULT 1,
                    created_at DATETIME DEFAULT GETDATE(),
                    last_login DATETIME
                )
            """)
        print("Created users table.")


def cmd_add(args):
    db = DatabaseManager()
    _ensure_users_table(db)

    # Check for duplicates
    existing = db.execute_query(
        "SELECT orcid_id FROM users WHERE orcid_id = ?", (args.orcid,)
    )
    if existing:
        print(f"Error: User with ORCID {args.orcid} already exists.")
        sys.exit(1)

    db.execute_update(
        "INSERT INTO users (orcid_id, display_name, email, role) VALUES (?, ?, ?, ?)",
        (args.orcid, args.name, args.email, args.role),
    )
    print(f"Added user: {args.orcid} (name={args.name}, role={args.role})")


def cmd_list(args):
    db = DatabaseManager()
    _ensure_users_table(db)

    users = db.execute_query(
        "SELECT orcid_id, display_name, email, role, is_active, last_login "
        "FROM users ORDER BY created_at"
    )

    if not users:
        print("No users found.")
        return

    # Simple table output
    header = f"{'ORCID iD':<22} {'Name':<25} {'Email':<30} {'Role':<8} {'Active':<8} {'Last Login'}"
    print(header)
    print("-" * len(header))
    for u in users:
        active = "Yes" if u['is_active'] else "No"
        last_login = u['last_login'] or 'Never'
        print(
            f"{u['orcid_id']:<22} "
            f"{(u['display_name'] or ''):<25} "
            f"{(u['email'] or ''):<30} "
            f"{u['role']:<8} "
            f"{active:<8} "
            f"{last_login}"
        )
    print(f"\nTotal: {len(users)} user(s)")


def cmd_deactivate(args):
    db = DatabaseManager()
    rows = db.execute_update(
        "UPDATE users SET is_active = 0 WHERE orcid_id = ?", (args.orcid,)
    )
    if rows:
        print(f"Deactivated user: {args.orcid}")
    else:
        print(f"Error: No user found with ORCID {args.orcid}")
        sys.exit(1)


def cmd_activate(args):
    db = DatabaseManager()
    rows = db.execute_update(
        "UPDATE users SET is_active = 1 WHERE orcid_id = ?", (args.orcid,)
    )
    if rows:
        print(f"Activated user: {args.orcid}")
    else:
        print(f"Error: No user found with ORCID {args.orcid}")
        sys.exit(1)


def cmd_set_role(args):
    db = DatabaseManager()
    rows = db.execute_update(
        "UPDATE users SET role = ? WHERE orcid_id = ?", (args.role, args.orcid)
    )
    if rows:
        print(f"Set role for {args.orcid} to '{args.role}'")
    else:
        print(f"Error: No user found with ORCID {args.orcid}")
        sys.exit(1)


def cmd_remove(args):
    db = DatabaseManager()
    rows = db.execute_update(
        "DELETE FROM users WHERE orcid_id = ?", (args.orcid,)
    )
    if rows:
        print(f"Removed user: {args.orcid}")
    else:
        print(f"Error: No user found with ORCID {args.orcid}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Haplosearch user management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # --- add ---
    p_add = subparsers.add_parser("add", help="Add a new user to the whitelist")
    p_add.add_argument("--orcid", required=True, help="ORCID iD (e.g. 0000-0001-2345-6789)")
    p_add.add_argument("--name", default=None, help="Display name")
    p_add.add_argument("--email", default=None, help="Email address")
    p_add.add_argument("--role", default="user", choices=["admin", "user"], help="User role")

    # --- list ---
    subparsers.add_parser("list", help="List all users")

    # --- deactivate ---
    p_deact = subparsers.add_parser("deactivate", help="Deactivate a user (deny login)")
    p_deact.add_argument("--orcid", required=True, help="ORCID iD")

    # --- activate ---
    p_act = subparsers.add_parser("activate", help="Re-activate a user")
    p_act.add_argument("--orcid", required=True, help="ORCID iD")

    # --- set-role ---
    p_role = subparsers.add_parser("set-role", help="Change a user's role")
    p_role.add_argument("--orcid", required=True, help="ORCID iD")
    p_role.add_argument("--role", required=True, choices=["admin", "user"], help="New role")

    # --- remove ---
    p_rm = subparsers.add_parser("remove", help="Permanently remove a user")
    p_rm.add_argument("--orcid", required=True, help="ORCID iD")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "add": cmd_add,
        "list": cmd_list,
        "deactivate": cmd_deactivate,
        "activate": cmd_activate,
        "set-role": cmd_set_role,
        "remove": cmd_remove,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
