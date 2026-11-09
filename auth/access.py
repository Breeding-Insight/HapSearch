"""Per-species access control.

Admins see every species. A ``user`` sees only the species named on their
allowlist record (see auth/user_store.py); with none named they see nothing.

The species picker lists only the allowed species, but the picker alone is not
the protection: every page callback reads the species, locus or
microhaplotype it works on from values the browser sends back. So every Dash
callback request goes through ``check_dash_request`` (registered in app.py),
which looks up the species behind each of those values and refuses the
request if any of them is not allowed.

The search queries treat an empty species as "every species", so a request
from a restricted user whose species value is empty is answered with no update
(``species_missing``) instead of being run.

Every component id a callback reads must be listed here: in the checked sets
when its value names a species, locus or microhaplotype, or in
``UNCHECKED_SAFE`` with the reason it needs no check. The test
tests/test_species_access.py fails on any id in neither, so a new or renamed
component cannot slip past this module unnoticed.
"""

import logging
import time
from typing import Any, Dict, FrozenSet, Iterable, List, Optional

from flask import g, session

from auth.user_store import normalize_species

logger = logging.getLogger(__name__)

ADMIN_ROLE = "admin"

# How long a session's role and species are trusted before the allowlist is
# read again, so a change to someone's access (or a deactivation) applies
# within minutes rather than at their next sign-in.
ACCESS_REFRESH_SECONDS = 300

# (component id, property) whose value is a species id.
SPECIES_PROPS = {
    ("selected-species-store", "data"),
    ("global-species-dropdown", "value"),
}
# (component id, property) whose value is a locus id, or a dict holding one
# under "marker_id".
MARKER_PROPS = {
    ("marker-detail-store", "data"),
    ("navigate-to-marker-store", "data"),
    ("marker-alignment-store", "data"),
}
# (component id, property) whose value is a dict holding a microhaplotype name
# under "haplotype_name".
HAPLOTYPE_PROPS = {
    ("navigate-to-haplotype-store", "data"),
}
# Pattern-matching component types whose "index" is a locus id or a
# microhaplotype name.
MARKER_PATTERN_TYPES = {"marker-list-item", "view-marker-btn"}
HAPLOTYPE_PATTERN_TYPES = {"haplotype-list-item"}

# Component ids (or pattern types) whose values need no species check, and
# why. "Scoped" means the callback only uses the value together with the
# checked species (e.g. AND species = ?), so a value from another species
# just finds nothing.
_SCOPED = "used only together with the checked species"
_UI = "page state only; never used to look anything up"
_ECHO = "data the browser already received, shown again without a database lookup"
UNCHECKED_SAFE = {
    "global-programs-dropdown": _SCOPED,
    "global-allele-filter": _SCOPED,
    "allele-filter-clear": _UI,
    "overview-filter-shared-all": _UI,
    "overview-load-accumulation-btn": _UI,
    "overview-sharing-chart": _SCOPED,
    "overview-sharing-chart-state": _SCOPED,
    "haplotype-chromosome-filter": _SCOPED,
    "haplotype-marker-filter": _SCOPED,
    "haplotype-sequence-search": _SCOPED,
    "haplotype-sample-filter": _SCOPED,
    "haplotype-frequency-range": _SCOPED,
    "haplotype-frequency-min-input": _SCOPED,
    "haplotype-frequency-max-input": _SCOPED,
    "haplotype-frequency-reset": _UI,
    "haplotype-exclude-missing-samples": _SCOPED,
    "haplotype-results-page": _UI,
    "haplotype-page-prev": _UI,
    "haplotype-page-next": _UI,
    "haplotype-detail-content": _ECHO,
    "haplotype-left-panel-minimized": _UI,
    "haplotype-minimize-btn": _UI,
    "haplotype-expand-rail": _UI,
    "marker-chromosome-filter": _SCOPED,
    "marker-search-input": _SCOPED,
    "marker-sequence-search-input": _SCOPED,
    "marker-results-page": _UI,
    "marker-page-prev": _UI,
    "marker-page-next": _UI,
    "marker-left-panel-minimized": _UI,
    "marker-minimize-btn": _UI,
    "marker-expand-rail": _UI,
    "msa-widen-btn": _UI,
    "show-original-btn": _UI,
    "samples-data-store": _ECHO,
    "samples-search-input": _ECHO,
    "samples-table-page": _UI,
    "samples-pagination": _UI,
    "samples-collapse": _UI,
    "samples-download-btn": _UI,
    "samples-download-filename": _ECHO,
    "samples-download-name-store": _ECHO,
    "toggle-samples": _UI,
    "toggle-projects": _UI,
    "projects-collapse": _UI,
    "toggle-collaborators": _UI,
    "collaborators-collapse": _UI,
    "main-tabs": _UI,
    "app-initialized-store": _UI,
}

# Ids this module checks; with UNCHECKED_SAFE, every id a callback may read.
CHECKED_IDS = (
    {comp_id for comp_id, _ in SPECIES_PROPS | MARKER_PROPS | HAPLOTYPE_PROPS}
    | MARKER_PATTERN_TYPES | HAPLOTYPE_PATTERN_TYPES
    | {"overview-genome-plot", "global-species-dropdown"}
)

_IN_CHUNK = 500


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def store_access(role: str, species: Iterable[str], *, refreshable: bool = True) -> None:
    """Record the signed-in user's role and species in the session."""
    session["user_role"] = role or "user"
    session["user_species"] = normalize_species(species)
    session["access_checked_at"] = time.time() if refreshable else None


def refresh_access() -> bool:
    """Re-read the allowlist when the session's copy is stale.

    Returns False when the user is no longer allowed in at all (removed or
    deactivated); the caller should then end the session. Sessions created by
    a dev bypass are not on the allowlist and are never refreshed.
    """
    checked_at = session.get("access_checked_at")
    if checked_at is None or time.time() - checked_at < ACCESS_REFRESH_SECONDS:
        return True
    try:
        from auth.user_store import get_user_store
        user = get_user_store().get_active_user(session.get("orcid_id"))
    except Exception:
        # Keep the current access if the store is briefly unreachable.
        logger.exception("Access refresh failed for %s", session.get("orcid_id"))
        return True
    if not user:
        logger.info("Access revoked: orcid_id=%s", session.get("orcid_id"))
        return False
    store_access(user.get("role"), user.get("species"))
    return True


def is_admin() -> bool:
    return session.get("user_role") == ADMIN_ROLE


def allowed_species_ids(db=None) -> Optional[FrozenSet[int]]:
    """Return the ids of the species the current user may see.

    None means every species (admins). Names on the allowlist are matched to
    a species' scientific or common name, ignoring case; names that match no
    species are ignored. The answer is cached for the rest of the request.
    """
    if is_admin():
        return None
    if "allowed_species_ids" in g:
        return g.allowed_species_ids
    names = normalize_species(session.get("user_species"))
    ids = frozenset()
    if names:
        if db is None:
            from database.db_manager import DatabaseManager
            db = DatabaseManager()
        marks = ",".join("?" * len(names))
        rows = db.execute_query(
            f"SELECT id FROM species WHERE name IN ({marks}) OR common_name IN ({marks})",
            tuple(names) * 2,
        )
        ids = frozenset(int(row["id"]) for row in rows)
    g.allowed_species_ids = ids
    return ids


def can_access_species(species_id, db=None) -> bool:
    allowed = allowed_species_ids(db)
    if allowed is None:
        return True
    try:
        return int(species_id) in allowed
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Dash request guard
# ---------------------------------------------------------------------------

def _flatten(items) -> Iterable[Dict[str, Any]]:
    """Yield every {id, property, value} entry; wildcard inputs arrive as lists."""
    for item in items or []:
        if isinstance(item, list):
            yield from _flatten(item)
        elif isinstance(item, dict):
            yield item


def _marker_from(value) -> Optional[str]:
    if isinstance(value, dict):
        value = value.get("marker_id")
    return value if isinstance(value, str) and value else None


def collect_references(payload: Dict[str, Any]) -> Dict[str, set]:
    """Pull the species ids, locus ids and microhaplotype names out of a
    Dash callback request body."""
    refs = {"species": set(), "markers": set(), "haplotypes": set()}
    entries = list(_flatten(payload.get("inputs"))) + list(_flatten(payload.get("state")))
    for entry in entries:
        comp_id, prop, value = entry.get("id"), entry.get("property"), entry.get("value")
        if isinstance(comp_id, dict):
            kind, index = comp_id.get("type"), comp_id.get("index")
            if kind in MARKER_PATTERN_TYPES and isinstance(index, str):
                refs["markers"].add(index)
            elif kind in HAPLOTYPE_PATTERN_TYPES and isinstance(index, str):
                refs["haplotypes"].add(index)
            continue
        key = (comp_id, prop)
        if value in (None, ""):
            continue
        if key in SPECIES_PROPS:
            refs["species"].add(value)
        elif key in MARKER_PROPS:
            marker = _marker_from(value)
            if marker:
                refs["markers"].add(marker)
        elif key in HAPLOTYPE_PROPS:
            name = value.get("haplotype_name") if isinstance(value, dict) else None
            if isinstance(name, str) and name:
                refs["haplotypes"].add(name)
        elif key == ("overview-genome-plot", "clickData") and isinstance(value, dict):
            for point in value.get("points") or []:
                custom = point.get("customdata") if isinstance(point, dict) else None
                if isinstance(custom, list) and custom and isinstance(custom[0], str):
                    refs["markers"].add(custom[0])
    return refs


def _species_of(db, table_sql: str, values: List[str]) -> set:
    found = set()
    for start in range(0, len(values), _IN_CHUNK):
        chunk = values[start:start + _IN_CHUNK]
        rows = db.execute_query(
            table_sql.format(marks=",".join("?" * len(chunk))), tuple(chunk)
        )
        found.update(int(row["species_id"]) for row in rows)
    return found


def species_missing(payload: Dict[str, Any]) -> bool:
    """True when a restricted user's request carries an empty species value.

    Searches run with no species return every species, so such a request must
    not run. Admins are never affected.
    """
    if is_admin():
        return False
    entries = list(_flatten(payload.get("inputs"))) + list(_flatten(payload.get("state")))
    return any(
        (entry.get("id"), entry.get("property")) in SPECIES_PROPS
        and entry.get("value") in (None, "")
        for entry in entries
    )


def check_dash_request(payload: Dict[str, Any], db=None) -> Optional[str]:
    """Return None when the request may run, otherwise why it may not."""
    allowed = allowed_species_ids(db)
    if allowed is None:
        return None
    refs = collect_references(payload)
    if not any(refs.values()):
        return None
    if db is None:
        from database.db_manager import DatabaseManager
        db = DatabaseManager()

    species = set()
    for value in refs["species"]:
        try:
            species.add(int(value))
        except (TypeError, ValueError):
            return f"invalid species id {value!r}"
    if refs["markers"]:
        species |= _species_of(db, """
            SELECT DISTINCT c.species_id
            FROM markers mk JOIN chromosomes c ON c.id = mk.chromosome_id
            WHERE mk.marker_id IN ({marks})
        """, sorted(refs["markers"]))
    if refs["haplotypes"]:
        species |= _species_of(db, """
            SELECT DISTINCT c.species_id
            FROM microhaplotypes m
            JOIN markers mk ON mk.id = m.marker_id
            JOIN chromosomes c ON c.id = mk.chromosome_id
            WHERE m.haplotype_name IN ({marks})
        """, sorted(refs["haplotypes"]))

    denied = species - allowed
    if denied:
        return f"species {sorted(denied)} not shared with this account"
    return None
