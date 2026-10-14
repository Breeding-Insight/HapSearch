"""Global program/allele filter shared by the app's tabs.

The filter has two parts, both set in the filter bar (or from the Filter by Programs tab's
sharing chart):

- programs: the program groups in play (default: every program)
- alleles: which of their alleles to keep, as a string value:
    "any"            alleles found in at least one selected program
    "all"            alleles found in every selected program
    "only:<group>"   alleles found in that program and no other selected one
    "pair:<a>|<b>"   alleles found in both programs (others may have them too)

Program membership comes from the presence artifacts, which only change when
the database is rebuilt, so it is cached per species and program selection.
"""

from functools import lru_cache
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from database.db_manager import DatabaseManager
from database.queries import get_microhaplotype_project_sharing_data

ANY = "any"
ALL = "all"
REMAINING_GROUP_ID = "all"  # the sharing query's "Remaining Locations" group


@lru_cache(maxsize=8)
def program_catalog(species_id: int) -> Tuple[Dict[str, str], ...]:
    """Every program group for a species, as ({"group_id", "label"}, ...)."""
    db = DatabaseManager()
    with db.shared_connection():
        data = get_microhaplotype_project_sharing_data(db, species_id)
    return tuple(
        {"group_id": group["group_id"], "label": group["label"]}
        for group in data.get("available_owner_groups") or []
    )


def default_program_ids(species_id: int) -> List[str]:
    """Every program except the catch-all "Remaining Locations" group."""
    return [
        group["group_id"]
        for group in program_catalog(species_id)
        if group["group_id"] != REMAINING_GROUP_ID
    ]


@lru_cache(maxsize=16)
def _sharing_data(species_id: int, program_ids: Tuple[str, ...]) -> dict:
    db = DatabaseManager()
    with db.shared_connection():
        return get_microhaplotype_project_sharing_data(
            db,
            species_id,
            max_intersections=0,
            selected_group_ids=list(program_ids),
            include_membership=True,
        )


def sharing_data(species_id: int, program_ids: Sequence[str]) -> dict:
    """Sharing intersections and per-allele membership for the selected programs."""
    return _sharing_data(species_id, tuple(sorted(program_ids or default_program_ids(species_id))))


def _populated_program_ids(data: dict) -> List[str]:
    """Selected programs that hold at least one allele."""
    populated = set()
    for groups in (data.get("microhaplotype_groups") or {}).values():
        populated.update(groups)
    return [
        group["group_id"]
        for group in data.get("owner_groups") or []
        if group["group_id"] in populated
    ]


@lru_cache(maxsize=32)
def _resolve(species_id: int, program_ids: Tuple[str, ...], allele_filter: str) -> Optional[FrozenSet[int]]:
    data = _sharing_data(species_id, program_ids)
    membership = data.get("microhaplotype_groups") or {}

    if allele_filter == ANY:
        if set(program_ids) >= set(default_program_ids(species_id)):
            return None  # every program: no restriction
        return frozenset(membership)
    if allele_filter == ALL:
        wanted = set(_populated_program_ids(data))
        return frozenset(m for m, groups in membership.items() if wanted and set(groups) >= wanted)
    if allele_filter.startswith("only:"):
        group_id = allele_filter[len("only:"):]
        return frozenset(m for m, groups in membership.items() if groups == (group_id,))
    if allele_filter.startswith("pair:"):
        first, _, second = allele_filter[len("pair:"):].partition("|")
        return frozenset(m for m, groups in membership.items() if first in groups and second in groups)
    return None


def resolve_allele_filter(species_id, program_ids, allele_filter) -> Optional[FrozenSet[int]]:
    """Microhaplotype ids the filter keeps, or None when it keeps everything."""
    if not species_id:
        return None
    if (allele_filter or ANY) == ANY and not program_ids:
        return None  # nothing chosen yet: no restriction, no lookup
    programs = tuple(sorted(program_ids or default_program_ids(species_id)))
    return _resolve(int(species_id), programs, allele_filter or ANY)


def allele_filter_options(species_id, program_ids) -> List[Dict[str, str]]:
    """Choices for the Alleles filter, labelled with the selected programs' names."""
    if not species_id:
        return []
    catalog = program_catalog(int(species_id))
    labels = {group["group_id"]: group["label"] for group in catalog}
    selected = set(program_ids or default_program_ids(species_id))
    # Catalog order, which the sharing chart also uses, so a pair clicked on
    # the chart ("pair:<first>|<second>") always matches one of these values.
    programs = [group["group_id"] for group in catalog if group["group_id"] in selected]
    options = [
        {"label": "All alleles in the selected programs", "value": ANY},
        {"label": "Shared by every selected program", "value": ALL},
    ]
    options += [{"label": f"Only in {labels[g]}", "value": f"only:{g}"} for g in programs]
    options += [
        {"label": f"Shared by {labels[a]} and {labels[b]}", "value": f"pair:{a}|{b}"}
        for index, a in enumerate(programs) for b in programs[index + 1:]
    ]
    return options
