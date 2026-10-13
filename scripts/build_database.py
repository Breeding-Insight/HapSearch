#!/usr/bin/env python3
"""Build the HapSearch SQLite database from a data repository.

Everything the database contains is described by a ``manifest.toml`` in the
data repository, normally ``data/hapSearch/manifest.toml`` (or ``{species}/data/hapSearch/``) next to the
HapSearch inputs (see docs/updating-data.md). The build always starts from an empty
database, runs every import in order, optimizes the file, checks the result and
compares it with the previous build. The output file is only replaced when every
check passes, so a failed build never leaves a half-built database behind.

    python scripts/build_database.py --data-repo ../alfalfa_haplotype_db

Paths in the manifest are relative to the manifest's folder; a path starting
with "/" is relative to the data repository root. Paths may use wildcards
(``*``): a FASTA pattern selects the highest version, every other single-file
pattern must match exactly one file, and ``{fasta}`` in a presence path stands
for the chosen FASTA's name without its extension. A source can also come from
another GitHub repository at a pinned tag or commit, using your git credentials
locally or GITHUB_TOKEN in Cloud Build.
"""

import argparse
import base64
import datetime
import glob
import gzip
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import config  # noqa: E402
from database.db_manager import DatabaseManager  # noqa: E402
from scripts.import_sample_presence import PRESENCE_FILE_SUFFIXES  # noqa: E402
from scripts.init_database import init_database  # noqa: E402

DEFAULT_MAX_SKIPPED_ALLELE_FRACTION = 0.02
FASTA_SUFFIXES = (".fa.gz", ".fasta.gz", ".fna.gz", ".fa", ".fasta", ".fna")
COMPARED_TABLES = [
    "species", "chromosomes", "markers", "microhaplotypes", "botloci",
    "projects", "samples", "contacts", "presence_artifacts",
]


class BuildError(RuntimeError):
    """A problem with the manifest, an input file or an import."""


@dataclass
class SpeciesInputs:
    name: str
    common_name: Optional[str]
    fasta: str
    botloci: Optional[str]
    sample_presence: List[str] = field(default_factory=list)
    project_presence: List[str] = field(default_factory=list)


@dataclass
class BuildPlan:
    manifest_path: str
    project_mapping: str
    owner_contacts: str
    species: List[SpeciesInputs]
    max_skipped_allele_fraction: float
    sources: Dict[str, str] = field(default_factory=dict)  # label -> commit/ref


def _log(message: str = "") -> None:
    print(message, flush=True)


def _git(args: List[str], cwd: str, token: Optional[str]) -> str:
    env = dict(os.environ)
    if token:
        # Pass the token as an HTTP header through git's environment config so
        # it never appears in a URL, the command line or the build log.
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        })
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise BuildError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def fetch_github_file(repo: str, ref: str, path: str, cache_dir: str) -> Tuple[str, str]:
    """Fetch one file from a GitHub repository at a tag, branch or commit.

    Returns the local path and the resolved commit SHA.
    """
    checkout = os.path.join(cache_dir, repo.replace("/", "__"), ref.replace("/", "__"))
    os.makedirs(checkout, exist_ok=True)
    token = os.getenv("GITHUB_TOKEN") or None
    if not os.path.isdir(os.path.join(checkout, ".git")):
        _git(["init", "-q"], checkout, token)
        _git(["remote", "add", "origin", f"https://github.com/{repo}.git"], checkout, token)
    # Blob filtering downloads only the file being checked out, not the history.
    _git(["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", ref], checkout, token)
    _git(["checkout", "-q", "FETCH_HEAD", "--", path], checkout, token)
    commit = _git(["rev-parse", "FETCH_HEAD"], checkout, token)
    local_path = os.path.join(checkout, path)
    if not os.path.isfile(local_path):
        raise BuildError(f"{path} not found in {repo}@{ref}")
    return local_path, commit


def _local_path(data_repo: str, base_dir: str, spec: str) -> str:
    """Resolve a manifest path: relative to the manifest, or to the repo with '/'."""
    if spec.startswith("/"):
        return os.path.normpath(os.path.join(data_repo, spec.lstrip("/")))
    return os.path.normpath(os.path.join(base_dir, spec))


def _has_wildcard(spec: str) -> bool:
    return any(char in spec for char in "*?[")


def _version_key(path: str):
    """Sort so that v055 > v054 and v100 > v99."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", os.path.basename(path))]


def fasta_stem(path: str) -> str:
    name = os.path.basename(path)
    for suffix in FASTA_SUFFIXES:
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return os.path.splitext(name)[0]


def _glob_files(pattern_path: str) -> List[str]:
    return sorted(path for path in glob.glob(pattern_path) if os.path.isfile(path))


def find_manifest(data_repo: str, manifest: Optional[str]) -> str:
    """Use --manifest if given, else the one in data/hapSearch/ or */data/hapSearch/."""
    if not os.path.isdir(data_repo):
        raise BuildError(
            f"Data repository not found at {data_repo}. Clone "
            "Breeding-Insight/alfalfa_haplotype_db there or pass --data-repo"
        )
    if manifest:
        path = manifest if os.path.isabs(manifest) else os.path.join(data_repo, manifest)
        if not os.path.isfile(path):
            raise BuildError(f"Manifest not found: {path}")
        return path
    candidates = [
        os.path.join(data_repo, "manifest.toml"),
        os.path.join(data_repo, "data", "hapSearch", "manifest.toml"),
    ] + sorted(
        os.path.join(data_repo, name, "data", "hapSearch", "manifest.toml")
        for name in os.listdir(data_repo)
    )
    found = [path for path in candidates if os.path.isfile(path)]
    if len(found) != 1:
        raise BuildError(
            "Expected one manifest.toml in data/hapSearch/ (or {species}/data/hapSearch/) "
            "of the data repository, "
            f"found {len(found)}; pass --manifest to choose"
        )
    return found[0]


def _resolve_source(spec, data_repo: str, base_dir: str, cache_dir: str,
                    plan_sources: Dict[str, str], label: str,
                    pick_newest: bool = False) -> str:
    """A source is a path or pattern in the data repo, or {repo, ref, path} on GitHub.

    A pattern must match exactly one file, unless ``pick_newest`` is set (for the
    FASTA), in which case the highest version is used.
    """
    if isinstance(spec, str):
        path = _local_path(data_repo, base_dir, spec)
        if _has_wildcard(spec):
            matches = _glob_files(path)
            if not matches:
                raise BuildError(f"{label}: {spec} matches no files in the data repository")
            if len(matches) > 1 and not pick_newest:
                names = ", ".join(os.path.relpath(match, data_repo) for match in matches)
                raise BuildError(
                    f"{label}: {spec} matches {len(matches)} files ({names}); "
                    "remove the extras or name one file in manifest.toml"
                )
            path = max(matches, key=_version_key)
        elif not os.path.isfile(path):
            raise BuildError(f"{label}: {spec} does not exist in the data repository")
        plan_sources[label] = os.path.relpath(path, data_repo)
        return path
    if isinstance(spec, dict) and {"repo", "ref", "path"} <= set(spec):
        _log(f"Fetching {label} from {spec['repo']}@{spec['ref']}:{spec['path']}")
        path, commit = fetch_github_file(spec["repo"], spec["ref"], spec["path"], cache_dir)
        plan_sources[label] = f"{spec['repo']}@{spec['ref']} ({commit[:12]})"
        return path
    raise BuildError(f"{label}: expected a path or {{ repo, ref, path }}, got {spec!r}")


def _expand_presence(spec, data_repo: str, base_dir: str, label: str, fasta: str,
                     plan_sources: Dict[str, str]) -> List[str]:
    """Presence inputs are files, folders of matrices or patterns, or a list of them.

    ``{fasta}`` is replaced with the chosen FASTA's name, so a project matrix
    named after its FASTA version follows the FASTA automatically.
    """
    items = spec if isinstance(spec, list) else [spec]
    stem = fasta_stem(fasta)
    files: List[str] = []
    for raw_item in items:
        item = raw_item.replace("{fasta}", stem)
        hint = f" (for FASTA {os.path.basename(fasta)})" if "{fasta}" in raw_item else ""
        path = _local_path(data_repo, base_dir, item)
        if _has_wildcard(item):
            matches = [
                match for match in _glob_files(path)
                if match.lower().endswith(PRESENCE_FILE_SUFFIXES)
            ]
            if not matches:
                raise BuildError(f"{label}: {item} matches no CSV/TSV files{hint}")
            files.extend(matches)
        elif os.path.isdir(path):
            matches = sorted(
                os.path.join(path, name) for name in os.listdir(path)
                if name.lower().endswith(PRESENCE_FILE_SUFFIXES)
            )
            if not matches:
                raise BuildError(f"{label}: no CSV/TSV files in {item}")
            files.extend(matches)
        elif os.path.isfile(path):
            files.append(path)
        else:
            raise BuildError(f"{label}: {item} does not exist in the data repository{hint}")
    if len(files) <= 3:
        plan_sources[label] = ", ".join(os.path.relpath(path, data_repo) for path in files)
    else:
        plan_sources[label] = f"{len(files)} files"
    return files


def load_plan(data_repo: str, cache_dir: str, manifest: Optional[str] = None) -> BuildPlan:
    manifest_path = find_manifest(data_repo, manifest)
    base_dir = os.path.dirname(manifest_path)
    with open(manifest_path, "rb") as handle:
        manifest = tomllib.load(handle)

    sources: Dict[str, str] = {}
    metadata = manifest.get("metadata", {})
    for key in ("project_mapping", "owner_contacts"):
        if key not in metadata:
            raise BuildError(f"manifest.toml: [metadata] needs {key}")

    species = []
    for entry in manifest.get("species", []):
        name = entry.get("name")
        if not name or "fasta" not in entry:
            raise BuildError("manifest.toml: every [[species]] needs name and fasta")
        fasta = _resolve_source(entry["fasta"], data_repo, base_dir, cache_dir, sources,
                                f"{name} FASTA", pick_newest=True)
        species.append(SpeciesInputs(
            name=name,
            common_name=entry.get("common_name"),
            fasta=fasta,
            botloci=(
                _resolve_source(entry["botloci"], data_repo, base_dir, cache_dir, sources,
                                f"{name} botloci")
                if entry.get("botloci") else None
            ),
            sample_presence=(
                _expand_presence(entry["sample_presence"], data_repo, base_dir,
                                 f"{name} sample presence", fasta, sources)
                if entry.get("sample_presence") else []
            ),
            project_presence=(
                _expand_presence(entry["project_presence"], data_repo, base_dir,
                                 f"{name} project presence", fasta, sources)
                if entry.get("project_presence") else []
            ),
        ))
    if not species:
        raise BuildError("manifest.toml: add at least one [[species]]")

    checks = manifest.get("checks", {})
    return BuildPlan(
        manifest_path=manifest_path,
        project_mapping=_resolve_source(metadata["project_mapping"], data_repo, base_dir,
                                        cache_dir, sources, "project mapping"),
        owner_contacts=_resolve_source(metadata["owner_contacts"], data_repo, base_dir,
                                       cache_dir, sources, "owner contacts"),
        species=species,
        max_skipped_allele_fraction=float(
            checks.get("max_skipped_allele_fraction", DEFAULT_MAX_SKIPPED_ALLELE_FRACTION)
        ),
        sources=sources,
    )


def _run_import(script: str, args: List[str], db_path: str) -> None:
    env = dict(os.environ)
    env.update({
        "SQLITE_DB_PATH": db_path,
        "SQLITE_READ_ONLY": "false",
        "HAPSEARCH_USER_STORE": "sqlite",
        "PYTHONWARNINGS": "ignore",
    })
    command = [sys.executable, os.path.join(REPO_ROOT, "scripts", script), *args]
    result = subprocess.run(command, env=env, cwd=REPO_ROOT)
    if result.returncode != 0:
        raise BuildError(f"{script} failed (exit {result.returncode}); see the output above")


def run_imports(plan: BuildPlan, db_path: str) -> None:
    metadata_args = [
        "--project-mapping", plan.project_mapping,
        "--owner-contacts", plan.owner_contacts,
        "--allow-custom-metadata-paths",
    ]
    for species in plan.species:
        _log(f"\n=== {species.name}: FASTA ===")
        fasta_args = [species.fasta, species.name, "--quiet"]
        if species.common_name:
            fasta_args += ["--common-name", species.common_name]
        _run_import("import_fasta.py", fasta_args, db_path)

        if species.botloci:
            _log(f"\n=== {species.name}: bottom loci ===")
            _run_import("import_botloci.py", [species.botloci, "--quiet"], db_path)

        for path in species.sample_presence:
            _log(f"\n=== {species.name}: sample presence {os.path.basename(path)} ===")
            _run_import(
                "import_sample_presence.py",
                [path, "--species-name", species.name, "--quiet", *metadata_args],
                db_path,
            )

        for path in species.project_presence:
            _log(f"\n=== {species.name}: project presence {os.path.basename(path)} ===")
            _run_import(
                "import_project_presence.py", [path, "--quiet", *metadata_args], db_path,
            )


def _count_matrix_rows(path: str) -> int:
    opener = gzip.open if path.lower().endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        return max(sum(1 for line in handle if line.strip()) - 1, 0)


def validate(plan: BuildPlan, db_path: str) -> List[str]:
    """Return a list of problems; an empty list means the build is good."""
    problems = []
    conn = sqlite3.connect(db_path)
    try:
        for species in plan.species:
            row = conn.execute(
                """
                SELECT sp.id,
                       (SELECT COUNT(*) FROM markers mk JOIN chromosomes c ON c.id = mk.chromosome_id
                         WHERE c.species_id = sp.id),
                       (SELECT COUNT(*) FROM microhaplotypes m JOIN markers mk ON mk.id = m.marker_id
                         JOIN chromosomes c ON c.id = mk.chromosome_id WHERE c.species_id = sp.id)
                FROM species sp WHERE sp.name = ?
                """,
                (species.name,),
            ).fetchone()
            if not row:
                problems.append(f"{species.name}: species was not created")
                continue
            if not row[1] or not row[2]:
                problems.append(f"{species.name}: no markers or microhaplotypes were imported")

            for path, entity_type in (
                [(p, "sample") for p in species.sample_presence]
                + [(p, "project") for p in species.project_presence]
            ):
                artifact = conn.execute(
                    """
                    SELECT microhaplotype_count, entity_count, presence_count
                    FROM presence_artifacts
                    WHERE source_path = ? AND entity_type = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (path, entity_type),
                ).fetchone()
                name = os.path.basename(path)
                if not artifact:
                    problems.append(f"{name}: no {entity_type} presence data was stored")
                    continue
                matched, entities, present = artifact
                if not entities or not present:
                    problems.append(f"{name}: stored 0 {entity_type}s or 0 presence calls")
                rows = _count_matrix_rows(path)
                skipped = max(rows - matched, 0)
                if rows and skipped / rows > plan.max_skipped_allele_fraction:
                    problems.append(
                        f"{name}: {skipped:,} of {rows:,} alleles ({skipped / rows:.1%}) are not "
                        f"in the FASTA (limit {plan.max_skipped_allele_fraction:.0%}). Is the "
                        "FASTA version in manifest.toml the one these calls were made against?"
                    )
    finally:
        conn.close()
    return problems


def table_counts(db_path: str) -> Dict[str, int]:
    if not db_path or not os.path.isfile(db_path):
        return {}
    conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    try:
        counts = {}
        for table in COMPARED_TABLES:
            try:
                counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            except sqlite3.Error:
                counts[table] = 0
        return counts
    finally:
        conn.close()


def write_build_info(db_path: str, plan: BuildPlan, data_repo: str) -> Dict[str, str]:
    """Record what went into this database so the live version can be traced."""
    with open(plan.manifest_path, "rb") as handle:
        manifest_sha = hashlib.sha256(handle.read()).hexdigest()
    try:
        data_commit = _git(["rev-parse", "HEAD"], data_repo, None)
    except BuildError:
        data_commit = "unknown (not a git checkout)"
    info = {
        "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "data_repo_commit": data_commit,
        "manifest_sha256": manifest_sha,
        "sources": json.dumps(plan.sources, sort_keys=True),
    }
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS build_info (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany("INSERT OR REPLACE INTO build_info (key, value) VALUES (?, ?)", info.items())
        conn.commit()
    finally:
        conn.close()
    return info


def build(data_repo: str, output: str, compare_to: Optional[str], cache_dir: str,
          manifest: Optional[str] = None) -> bool:
    staging = os.path.abspath(output) + ".building"
    try:
        return _build(data_repo, output, compare_to, cache_dir, manifest)
    finally:
        # A failed build must not leave a half-built file around.
        if os.path.exists(staging):
            os.remove(staging)


def _build(data_repo: str, output: str, compare_to: Optional[str], cache_dir: str,
           manifest: Optional[str]) -> bool:
    data_repo = os.path.abspath(data_repo)
    output = os.path.abspath(output)
    staging = output + ".building"

    try:
        plan = load_plan(data_repo, cache_dir, manifest)
    except BuildError as exc:
        _log(f"Error: {exc}")
        return False

    _log(f"Building {output} from {plan.manifest_path}")
    try:
        if not init_database(force=True, db_path=staging):
            return False
        run_imports(plan, staging)
        info = write_build_info(staging, plan, data_repo)
        _log("\nOptimizing...")
        DatabaseManager(db_path=staging, read_only=False).optimize(vacuum=True)
    except BuildError as exc:
        _log(f"\nBuild failed: {exc}")
        return False

    _log("\nChecking the result...")
    problems = validate(plan, staging)
    if problems:
        _log("Build failed checks; the existing database was not replaced:")
        for problem in problems:
            _log(f"  - {problem}")
        return False

    previous = table_counts(compare_to)
    current = table_counts(staging)
    _log(f"\n{'Table':<22}{'Rows':>14}{'Change':>12}")
    for table in COMPARED_TABLES:
        change = ""
        if previous:
            delta = current[table] - previous.get(table, 0)
            change = f"{delta:+,}" if delta else "-"
        _log(f"{table:<22}{current[table]:>14,}{change:>12}")

    os.replace(staging, output)
    size_mb = os.path.getsize(output) / 1024 / 1024
    _log(f"\nBuilt {output} ({size_mb:.1f} MB)")
    _log(f"  data repo commit: {info['data_repo_commit']}")
    for label, source in plan.sources.items():
        _log(f"  {label}: {source}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-repo",
        default=os.getenv(
            "HAPSEARCH_DATA_REPO", os.path.join(os.path.dirname(REPO_ROOT), "alfalfa_haplotype_db")
        ),
        help="Checkout of the data repository (default: ../alfalfa_haplotype_db or "
             "HAPSEARCH_DATA_REPO)",
    )
    parser.add_argument(
        "--manifest",
        help="Manifest path inside the data repository (default: the one "
             "{species}/data/hapSearch/manifest.toml)",
    )
    parser.add_argument("--output", default=config.SQLITE_DB_PATH, help="Database file to write")
    parser.add_argument(
        "--compare-to",
        help="Previous database to compare row counts with (default: the current output file)",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.path.join(REPO_ROOT, ".build-cache"),
        help="Where files fetched from other GitHub repositories are kept",
    )
    args = parser.parse_args()

    compare_to = args.compare_to or (args.output if os.path.isfile(args.output) else None)
    sys.exit(0 if build(args.data_repo, args.output, compare_to, args.cache_dir, args.manifest)
             else 1)


if __name__ == "__main__":
    main()
