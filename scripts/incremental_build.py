"""Reuse the previous database so a build only redoes the species that changed.

A full build imports and aligns every species from scratch, so its time grows
with the number of species. An incremental build starts from the last
published database instead: species whose inputs are unchanged are kept as
they are, changed species are deleted and imported again, species no longer
listed are deleted, and only microhaplotypes without an alignment are aligned.

The result must match what a full build would store (row ids aside), so a
build falls back to a full one whenever that cannot be guaranteed:

* the build code, the schema or R's pwalign differ from the previous build's
  (recorded as ``code_fingerprint`` in its build_info table);
* a changed species shares a project, an owner contact or a sample name with
  a kept species. Those rows are shared between species, and their content
  (or a sample's ``_rep#`` suffix) depends on which species is imported last.

What went into each species is recorded as ``species_inputs`` in build_info:
a hash of its name, common name and the content of every input file.
"""

import hashlib
import importlib
import inspect
import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files whose content decides what a build stores. Changing any of them makes
# the next build a full one. scripts/build_database.py itself is included, so
# an edit there is never mistaken for an unchanged build.
BUILD_CODE_FILES = (
    "schema_sqlite.sql",
    "scripts/build_database.py",
    "scripts/incremental_build.py",
    "scripts/init_database.py",
    "scripts/import_fasta.py",
    "scripts/import_botloci.py",
    "scripts/import_sample_presence.py",
    "scripts/import_project_presence.py",
    "scripts/presence_metadata.py",
    "scripts/align_microhaplotypes.py",
    "scripts/align_microhaplotypes.R",
    "database/presence_artifacts.py",
    "database/db_manager.py",
)

# The importers use only these functions from database/queries.py, which is
# otherwise the app's query code; hashing just them keeps app edits there
# from forcing a full rebuild.
BUILD_CODE_FUNCTIONS = (
    ("database.queries", "get_all_species"),
    ("database.queries", "get_botloci_count"),
    ("database.queries", "upsert_botloci"),
)

# A sample stored as '<name>_rep2' is the same sample name as '<name>'.
_REP_SUFFIX = re.compile(r"_rep\d+$", re.IGNORECASE)


def _hash_file(digest, path: str) -> None:
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)


def pwalign_version() -> str:
    """The installed pwalign version, which decides the stored alignments."""
    from scripts.align_microhaplotypes import AlignmentError, find_rscript

    try:
        rscript = find_rscript()
    except AlignmentError:
        return "unavailable"  # the alignment step then explains what to install
    result = subprocess.run(
        [rscript, "-e", 'cat(as.character(packageVersion("pwalign")))'],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def code_fingerprint(aligner_version: Optional[str] = None) -> str:
    """Hash of the build code and the aligner version."""
    digest = hashlib.sha256()
    for relative in BUILD_CODE_FILES:
        digest.update(relative.encode() + b"\0")
        _hash_file(digest, os.path.join(REPO_ROOT, relative))
    for module_name, function_name in BUILD_CODE_FUNCTIONS:
        module = importlib.import_module(module_name)
        digest.update(f"{module_name}.{function_name}\0".encode())
        digest.update(inspect.getsource(getattr(module, function_name)).encode())
    digest.update(b"pwalign\0" + (aligner_version or pwalign_version()).encode())
    return digest.hexdigest()


def species_fingerprint(species, plan) -> str:
    """Hash of everything that decides one species' rows in the database.

    Covers its name, common name and each input file's name and content, in
    import order, plus the data repository's project mapping and contacts.
    """
    digest = hashlib.sha256()
    digest.update(json.dumps([species.name, species.common_name]).encode() + b"\0")
    files = (
        [("fasta", species.fasta)]
        + ([("botloci", species.botloci)] if species.botloci else [])
        + [("sample", path) for path in species.sample_presence]
        + [("project", path) for path in species.project_presence]
        + [("mapping", plan.project_mapping), ("contacts", plan.owner_contacts)]
    )
    for role, path in files:
        digest.update(f"{role}\0{os.path.basename(path)}\0".encode())
        _hash_file(digest, path)
        digest.update(b"\0")
    return digest.hexdigest()


def read_build_info(db_path: str) -> Dict[str, str]:
    """The previous build's build_info, or {} when it has none."""
    try:
        conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        return dict(conn.execute("SELECT key, value FROM build_info").fetchall())
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


@dataclass
class ReusePlan:
    """Which species an incremental build keeps, rebuilds and deletes."""
    kept: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    full_build_reason: Optional[str] = None  # set when the build must start from scratch

    @property
    def incremental(self) -> bool:
        return self.full_build_reason is None


def plan_reuse(previous_db: Optional[str], fingerprint: str,
               species_inputs: Dict[str, str]) -> ReusePlan:
    """Decide what an incremental build can keep from previous_db.

    species_inputs maps every species in this build to its fingerprint, in
    import order.
    """
    if not previous_db or not os.path.isfile(previous_db):
        return ReusePlan(full_build_reason="there is no previous database")
    info = read_build_info(previous_db)
    if info.get("code_fingerprint") != fingerprint:
        return ReusePlan(full_build_reason=(
            "the build code, schema or pwalign changed since the previous database was built"
            if info.get("code_fingerprint") else
            "the previous database does not record how it was built"
        ))
    try:
        previous_inputs = json.loads(info.get("species_inputs") or "{}")
    except json.JSONDecodeError:
        previous_inputs = {}
    if not previous_inputs:
        return ReusePlan(full_build_reason="the previous database does not record its species inputs")

    plan = ReusePlan()
    for name, digest in species_inputs.items():
        (plan.kept if previous_inputs.get(name) == digest else plan.changed).append(name)
    plan.removed = [name for name in previous_inputs if name not in species_inputs]
    if not plan.kept:
        plan.full_build_reason = "every species changed"
    return plan


# --- Rows that belong to a species ------------------------------------------

def _species_id(conn: sqlite3.Connection, name: str) -> Optional[int]:
    row = conn.execute("SELECT id FROM species WHERE name = ?", (name,)).fetchone()
    return int(row[0]) if row else None


def species_projects(conn: sqlite3.Connection, species_id: int) -> Set[str]:
    """Project codes the species' samples or presence matrices refer to."""
    rows = conn.execute(
        """
        SELECT p.project_code FROM projects p WHERE p.id IN (
            SELECT project_id FROM samples WHERE species_id = :sid
            UNION SELECT project_id FROM presence_artifacts
                  WHERE species_id = :sid AND project_id IS NOT NULL
            UNION SELECT pb.entity_id FROM presence_bitmaps pb
                  JOIN presence_artifacts pa ON pa.id = pb.artifact_id
                  WHERE pa.species_id = :sid AND pa.entity_type = 'project'
        )
        """,
        {"sid": species_id},
    ).fetchall()
    return {str(row[0]).lower() for row in rows}


def species_contacts(conn: sqlite3.Connection, species_id: int) -> Set[str]:
    """Names of the owner contacts linked to the species' projects."""
    codes = species_projects(conn, species_id)
    if not codes:
        return set()
    placeholders = ",".join("?" * len(codes))
    rows = conn.execute(
        f"""
        SELECT c.full_name FROM contacts c
        JOIN project_contacts pc ON pc.contact_id = c.id
        JOIN projects p ON p.id = pc.project_id
        WHERE lower(p.project_code) IN ({placeholders})
        """,
        tuple(codes),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}


def species_sample_names(conn: sqlite3.Connection, species_id: int) -> Set[str]:
    """The species' sample names, without any _rep# suffix."""
    rows = conn.execute("SELECT sample_code FROM samples WHERE species_id = ?", (species_id,))
    return {_REP_SUFFIX.sub("", str(row[0])).lower() for row in rows}


def shared_rows(conn: sqlite3.Connection, species: Iterable[str],
                others: Iterable[str]) -> Optional[str]:
    """Describe the first project, contact or sample name `species` share with `others`."""
    def collect(names, reader):
        found: Set[str] = set()
        for name in names:
            sid = _species_id(conn, name)
            if sid is not None:
                found |= reader(conn, sid)
        return found

    species, others = list(species), list(others)
    for label, reader in (("project", species_projects), ("owner contact", species_contacts),
                          ("sample name", species_sample_names)):
        overlap = collect(species, reader) & collect(others, reader)
        if overlap:
            example = sorted(overlap)[0]
            return f"{', '.join(species)} and {', '.join(others)} share the {label} '{example}'"
    return None


def unattributed_artifacts(conn: sqlite3.Connection) -> int:
    """Presence matrices that span several species, which cannot be deleted per species."""
    return conn.execute("SELECT COUNT(*) FROM presence_artifacts WHERE species_id IS NULL").fetchone()[0]


def delete_species(conn: sqlite3.Connection, name: str) -> None:
    """Delete one species and every row that belongs only to it."""
    sid = _species_id(conn, name)
    if sid is None:
        return
    conn.execute("DROP TABLE IF EXISTS temp.del_markers")
    conn.execute("DROP TABLE IF EXISTS temp.del_mh")
    conn.execute(
        "CREATE TEMP TABLE del_markers AS SELECT mk.id, mk.marker_id FROM markers mk "
        "JOIN chromosomes c ON c.id = mk.chromosome_id WHERE c.species_id = ?",
        (sid,),
    )
    conn.execute(
        "CREATE TEMP TABLE del_mh AS SELECT id FROM microhaplotypes "
        "WHERE marker_id IN (SELECT id FROM del_markers)"
    )
    statements = [
        ("DELETE FROM microhaplotype_alignments WHERE microhaplotype_id IN (SELECT id FROM del_mh) "
         "OR reference_id IN (SELECT id FROM del_mh)", ()),
        ("DELETE FROM microhaplotype_presence_summary WHERE species_id = ? "
         "OR microhaplotype_id IN (SELECT id FROM del_mh)", (sid,)),
        ("DELETE FROM presence_bitmaps WHERE artifact_id IN "
         "(SELECT id FROM presence_artifacts WHERE species_id = ?)", (sid,)),
        ("DELETE FROM presence_artifacts WHERE species_id = ?", (sid,)),
        ("DELETE FROM microhaplotype_samples WHERE microhaplotype_id IN (SELECT id FROM del_mh) "
         "OR sample_id IN (SELECT id FROM samples WHERE species_id = ?)", (sid,)),
        ("DELETE FROM samples WHERE species_id = ?", (sid,)),
        ("DELETE FROM variants WHERE marker_id IN (SELECT id FROM del_markers)", ()),
        ("DELETE FROM botloci WHERE marker_id IN (SELECT marker_id FROM del_markers)", ()),
        ("DELETE FROM microhaplotypes WHERE id IN (SELECT id FROM del_mh)", ()),
        ("DELETE FROM markers WHERE id IN (SELECT id FROM del_markers)", ()),
        ("DELETE FROM chromosomes WHERE species_id = ?", (sid,)),
        ("DELETE FROM species WHERE id = ?", (sid,)),
    ]
    for sql, params in statements:
        conn.execute(sql, params)
    conn.execute("DROP TABLE temp.del_markers")
    conn.execute("DROP TABLE temp.del_mh")


def delete_unused_projects_and_contacts(conn: sqlite3.Connection) -> None:
    """Drop projects and contacts no remaining species refers to.

    A full build only creates a project when a presence matrix refers to it,
    and a contact when a project links it, so after deleting a species the
    rows nothing refers to are exactly the ones a full build would not have.
    """
    conn.execute(
        """
        DELETE FROM projects WHERE id NOT IN (
            SELECT project_id FROM samples
            UNION SELECT project_id FROM presence_artifacts WHERE project_id IS NOT NULL
            UNION SELECT pb.entity_id FROM presence_bitmaps pb
                  JOIN presence_artifacts pa ON pa.id = pb.artifact_id
                  WHERE pa.entity_type = 'project'
        )
        """
    )
    conn.execute("DELETE FROM project_contacts WHERE project_id NOT IN (SELECT id FROM projects)")
    conn.execute("DELETE FROM contacts WHERE id NOT IN (SELECT contact_id FROM project_contacts)")
