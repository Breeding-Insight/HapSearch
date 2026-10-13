#!/usr/bin/env python3
"""CLI tool for managing Haplosearch users.

Works on the configured user store (HAPSEARCH_USER_STORE), or the one named
with --store. Firestore uses your Application Default Credentials, e.g. after
`gcloud auth application-default login`, plus GOOGLE_CLOUD_PROJECT and
FIRESTORE_DATABASE.

Usage:
    python scripts/manage_users.py add --orcid 0000-0001-2345-6789 --name "Jane Doe" --role admin
    python scripts/manage_users.py add --orcid 0000-0002-3456-7890 --name "Lab Member"
    python scripts/manage_users.py list
    python scripts/manage_users.py deactivate --orcid 0000-0002-3456-7890
    python scripts/manage_users.py activate --orcid 0000-0002-3456-7890
    python scripts/manage_users.py set-role --orcid 0000-0002-3456-7890 --role admin
    python scripts/manage_users.py remove --orcid 0000-0002-3456-7890
    python scripts/manage_users.py --store firestore copy-from-sqlite
"""

import argparse
import sys
import os
from datetime import datetime, timezone

# Ensure project root is on the path so we can import config / database
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth.user_store import (  # noqa: E402
    SqliteUserStore,
    UserExistsError,
    create_user_store,
)


def _fail(message):
    print(f"Error: {message}")
    sys.exit(1)


def _report(found, success_message, orcid):
    if found:
        print(success_message)
    else:
        _fail(f"No user found with ORCID {orcid}")


def cmd_add(store, args):
    try:
        store.add_user(args.orcid, args.name, args.email, args.role)
    except (UserExistsError, ValueError) as exc:
        _fail(exc)
    print(f"Added user: {args.orcid} (name={args.name}, role={args.role})")


def cmd_list(store, args):
    users = store.list_users()

    if not users:
        print("No users found.")
        return

    # Simple table output
    header = f"{'ORCID iD':<22} {'Name':<25} {'Email':<30} {'Role':<8} {'Active':<8} {'Added'}"
    print(header)
    print("-" * len(header))
    for u in users:
        active = "Yes" if u['is_active'] else "No"
        print(
            f"{u['orcid_id']:<22} "
            f"{(u['display_name'] or ''):<25} "
            f"{(u['email'] or ''):<30} "
            f"{u['role']:<8} "
            f"{active:<8} "
            f"{u['created_at'] or ''}"
        )
    print(f"\nTotal: {len(users)} user(s)")


def cmd_deactivate(store, args):
    _report(store.set_active(args.orcid, False), f"Deactivated user: {args.orcid}", args.orcid)


def cmd_activate(store, args):
    _report(store.set_active(args.orcid, True), f"Activated user: {args.orcid}", args.orcid)


def cmd_set_role(store, args):
    _report(
        store.set_role(args.orcid, args.role),
        f"Set role for {args.orcid} to '{args.role}'",
        args.orcid,
    )


def cmd_remove(store, args):
    _report(store.remove_user(args.orcid), f"Removed user: {args.orcid}", args.orcid)


def _parse_sqlite_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def cmd_copy_from_sqlite(store, args):
    """Copy the SQLite allowlist into Firestore, skipping people already there."""
    if store.backend != "firestore":
        _fail("copy-from-sqlite writes to Firestore; run it with --store firestore")

    copied = skipped = 0
    for user in SqliteUserStore().list_users():
        try:
            store.add_user(
                user["orcid_id"],
                user["display_name"],
                user["email"],
                user["role"],
                is_active=user["is_active"],
                created_at=_parse_sqlite_time(user["created_at"]),
            )
            copied += 1
        except UserExistsError:
            skipped += 1
        except ValueError as exc:
            print(f"Skipped {user['orcid_id']}: {exc}")
            skipped += 1
    print(f"Copied {copied} user(s) to Firestore; skipped {skipped}.")


def main():
    parser = argparse.ArgumentParser(
        description="Haplosearch user management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--store",
        choices=["sqlite", "firestore"],
        help="User store to manage (default: HAPSEARCH_USER_STORE)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    p_add = subparsers.add_parser("add", help="Add a new user to the whitelist")
    p_add.add_argument("--orcid", required=True, help="ORCID iD (e.g. 0000-0001-2345-6789)")
    p_add.add_argument("--name", default=None, help="Display name")
    p_add.add_argument("--email", default=None, help="Email address")
    p_add.add_argument("--role", default="user", choices=["admin", "user"], help="User role")

    subparsers.add_parser("list", help="List all users")

    p_deact = subparsers.add_parser("deactivate", help="Deactivate a user (deny login)")
    p_deact.add_argument("--orcid", required=True, help="ORCID iD")

    p_act = subparsers.add_parser("activate", help="Re-activate a user")
    p_act.add_argument("--orcid", required=True, help="ORCID iD")

    p_role = subparsers.add_parser("set-role", help="Change a user's role")
    p_role.add_argument("--orcid", required=True, help="ORCID iD")
    p_role.add_argument("--role", required=True, choices=["admin", "user"], help="New role")

    p_rm = subparsers.add_parser("remove", help="Permanently remove a user")
    p_rm.add_argument("--orcid", required=True, help="ORCID iD")

    subparsers.add_parser(
        "copy-from-sqlite",
        help="Copy users from the SQLite database into Firestore (use with --store firestore)",
    )

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
        "copy-from-sqlite": cmd_copy_from_sqlite,
    }
    commands[args.command](create_user_store(args.store), args)


if __name__ == "__main__":
    main()
