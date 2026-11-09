#!/usr/bin/env python3
"""CLI tool for managing Haplosearch users.

Works on the configured user store (HAPSEARCH_USER_STORE), or the one named
with --store. Firestore uses your Application Default Credentials, e.g. after
`gcloud auth application-default login`, plus GOOGLE_CLOUD_PROJECT and
FIRESTORE_DATABASE.

Usage:
    python scripts/manage_users.py add --orcid 0000-0001-2345-6789 --name "Jane Doe" --role admin
    python scripts/manage_users.py add --orcid 0000-0002-3456-7890 --name "Lab Member" --species "Medicago sativa"
    python scripts/manage_users.py list
    python scripts/manage_users.py deactivate --orcid 0000-0002-3456-7890
    python scripts/manage_users.py activate --orcid 0000-0002-3456-7890
    python scripts/manage_users.py set-role --orcid 0000-0002-3456-7890 --role admin
    python scripts/manage_users.py set-species --orcid 0000-0002-3456-7890 --species Alfalfa Pecan
    python scripts/manage_users.py grant-species --orcid 0000-0002-3456-7890 --species Blueberry
    python scripts/manage_users.py revoke-species --orcid 0000-0002-3456-7890 --species Pecan
    python scripts/manage_users.py remove --orcid 0000-0002-3456-7890
    python scripts/manage_users.py --store firestore copy-from-sqlite

Species are named by scientific or common name. Admins see every species; a
user sees only the species listed for them, and none if the list is empty.
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
    normalize_orcid,
    normalize_species,
)


def _fail(message):
    print(f"Error: {message}")
    sys.exit(1)


def _report(found, success_message, orcid):
    if found:
        print(success_message)
    else:
        _fail(f"No user found with ORCID {orcid}")


def _known_species():
    """Scientific and common names in the local species table, lowercased.

    None when there is no local database to check against.
    """
    try:
        from database.db_manager import DatabaseManager
        rows = DatabaseManager().execute_query("SELECT name, common_name FROM species")
    except Exception:
        return None
    return {str(v).lower() for row in rows for v in (row["name"], row["common_name"]) if v}


def _warn_unknown_species(names):
    known = _known_species()
    if known is None:
        return
    for name in names:
        if name.lower() not in known:
            print(f"Warning: '{name}' matches no species in the local database; "
                  "it is saved but grants nothing until a species with that name exists.")


def _find_user(store, orcid):
    try:
        orcid = normalize_orcid(orcid)
    except ValueError as exc:
        _fail(exc)
    for user in store.list_users():
        if user["orcid_id"] == orcid:
            return user
    _fail(f"No user found with ORCID {orcid}")


def cmd_add(store, args):
    species = normalize_species(args.species)
    _warn_unknown_species(species)
    try:
        store.add_user(args.orcid, args.name, args.email, args.role, species)
    except (UserExistsError, ValueError) as exc:
        _fail(exc)
    print(f"Added user: {args.orcid} (name={args.name}, role={args.role}, "
          f"species={'all (admin)' if args.role == 'admin' else ', '.join(species) or 'none'})")


def cmd_list(store, args):
    users = store.list_users()

    if not users:
        print("No users found.")
        return

    # Simple table output
    header = (f"{'ORCID iD':<22} {'Name':<25} {'Email':<30} {'Role':<8} {'Active':<8} "
              f"{'Added':<20} {'Species'}")
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
            f"{(u['created_at'] or ''):<20} "
            f"{'all (admin)' if u['role'] == 'admin' else ', '.join(u['species']) or 'none'}"
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


def _save_species(store, orcid, species):
    try:
        orcid = normalize_orcid(orcid)
    except ValueError as exc:
        _fail(exc)
    _report(
        store.set_species(orcid, species),
        f"Species for {orcid}: {', '.join(species) or 'none'}",
        orcid,
    )


def cmd_set_species(store, args):
    species = normalize_species(args.species)
    _warn_unknown_species(species)
    _save_species(store, args.orcid, species)


def cmd_grant_species(store, args):
    added = normalize_species(args.species)
    _warn_unknown_species(added)
    current = _find_user(store, args.orcid)["species"]
    _save_species(store, args.orcid, normalize_species(current + added))


def cmd_revoke_species(store, args):
    removed = {name.lower() for name in normalize_species(args.species)}
    current = _find_user(store, args.orcid)["species"]
    _save_species(store, args.orcid, [n for n in current if n.lower() not in removed])


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
                user["species"],
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
    p_add.add_argument("--species", nargs="+", default=[],
                       help="Species the user may see (scientific or common names)")

    subparsers.add_parser("list", help="List all users")

    p_deact = subparsers.add_parser("deactivate", help="Deactivate a user (deny login)")
    p_deact.add_argument("--orcid", required=True, help="ORCID iD")

    p_act = subparsers.add_parser("activate", help="Re-activate a user")
    p_act.add_argument("--orcid", required=True, help="ORCID iD")

    p_role = subparsers.add_parser("set-role", help="Change a user's role")
    p_role.add_argument("--orcid", required=True, help="ORCID iD")
    p_role.add_argument("--role", required=True, choices=["admin", "user"], help="New role")

    for name, help_text in (
        ("set-species", "Replace the species a user may see"),
        ("grant-species", "Let a user see more species"),
        ("revoke-species", "Stop a user seeing some species"),
    ):
        p_species = subparsers.add_parser(name, help=help_text)
        p_species.add_argument("--orcid", required=True, help="ORCID iD")
        p_species.add_argument("--species", nargs="+", required=name != "set-species",
                               default=[], help="Scientific or common names")

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
        "set-species": cmd_set_species,
        "grant-species": cmd_grant_species,
        "revoke-species": cmd_revoke_species,
        "remove": cmd_remove,
        "copy-from-sqlite": cmd_copy_from_sqlite,
    }
    commands[args.command](create_user_store(args.store), args)


if __name__ == "__main__":
    main()
