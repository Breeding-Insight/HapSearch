"""Helpers for collaborator row rendering."""

from typing import Any, Dict, List, Optional


def build_collaborator_rows_from_contacts(
    contacts_data: Optional[List[Dict[str, Any]]]
) -> List[Dict[str, str]]:
    """Build de-duplicated collaborator rows from linked contact records only."""
    if not contacts_data:
        return []

    unique_contacts: Dict[str, Dict[str, str]] = {}
    for contact in contacts_data:
        name = (contact.get("full_name") or "").strip()
        if not name:
            continue

        email = (contact.get("email") or "").strip()
        institution = (contact.get("institution") or "").strip()
        location = (contact.get("location") or "").strip()

        dedupe_key = (
            email.lower()
            if email
            else f"{name.lower()}::{institution.lower()}::{location.lower()}"
        )
        if dedupe_key in unique_contacts:
            continue

        unique_contacts[dedupe_key] = {
            "Name": name,
            "Institution": institution or "—",
            "Location": location or "—",
            "Email": email or "—",
        }

    rows = list(unique_contacts.values())
    rows.sort(
        key=lambda r: (
            r["Location"] == "—" or r["Email"] == "—",
            r["Name"].lower(),
            r["Institution"].lower(),
        )
    )
    return rows
