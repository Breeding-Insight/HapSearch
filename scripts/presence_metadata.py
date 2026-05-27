#!/usr/bin/env python3
"""Shared helpers for metadata-driven presence imports."""

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


_DAI_TOKEN_RE = re.compile(r"(D[Aa][IiLl](?:\d{2})?-\d+)", re.IGNORECASE)
_DAI_TOKEN_NORMALIZE_DASH_RE = re.compile(r"(D[Aa][IiLl](?:\d{2})?)_(\d+)", re.IGNORECASE)
_INTERNAL_PROJECT_RE = re.compile(r"^P\d{2}$", re.IGNORECASE)
_VALIDATION_RE = re.compile(r"validation", re.IGNORECASE)


def read_matrix(csv_path: str) -> pd.DataFrame:
    """Read a CSV/TSV matrix using simple delimiter detection."""
    for sep in [",", "\t", ";"]:
        try:
            df = pd.read_csv(csv_path, sep=sep)
            if df.shape[1] >= 2:
                return df
        except Exception:
            pass
    return pd.read_csv(csv_path, sep=None, engine="python")


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def extract_dai_tokens(text: str) -> List[str]:
    """Extract ordered unique DAI/DAl tokens from free text."""
    seen = set()
    tokens: List[str] = []
    for match in _DAI_TOKEN_RE.finditer(_safe_text(text)):
        token = normalize_token(match.group(1))
        if token and token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def normalize_token(token: str) -> str:
    """Canonical token format for stable metadata joins."""
    value = _safe_text(token)
    if not value:
        return ""
    # Keep DAl form to match project headers in this repo's data.
    value = re.sub(r"^D[Aa][IiLl]", "DAl", value)
    return value


def normalize_genotyping_source(raw: str) -> str:
    """Normalize one or more DAI tokens to underscore-joined key."""
    tokens = extract_dai_tokens(raw)
    return "_".join(tokens)


def normalize_project_code(project_code: str) -> str:
    """Normalize project_code by using underscores outside DAI token internals."""
    code = _safe_text(project_code)
    if not code:
        return ""
    normalized = code.replace("-", "_")
    # Restore DAI token internal dash (e.g. DAl22_7011 -> DAl22-7011).
    return _DAI_TOKEN_NORMALIZE_DASH_RE.sub(r"\1-\2", normalized)


def get_mapping_for_project_code(
    project_code: str,
    mapping_by_project_code: Dict[str, Dict[str, str]],
) -> Optional[Dict[str, str]]:
    """Resolve mapping row by exact or normalized project_code key."""
    raw_code = _safe_text(project_code)
    if not raw_code:
        return None
    hit = mapping_by_project_code.get(raw_code)
    if hit:
        return hit
    return mapping_by_project_code.get(normalize_project_code(raw_code))


def parse_project_header(project_header: str) -> Dict[str, Optional[str]]:
    """Best-effort parse of project-level matrix header."""
    header = _safe_text(project_header)
    tokens = [t for t in header.split("_") if t]

    internal_project_id = tokens[0] if tokens and _INTERNAL_PROJECT_RE.match(tokens[0]) else None
    genotyping_source = normalize_genotyping_source(header) or None

    start_idx = 1 if internal_project_id else 0
    non_dai_tokens = [t for t in tokens[start_idx:] if not extract_dai_tokens(t)]

    owner = None
    informal_name = None
    if non_dai_tokens:
        if _VALIDATION_RE.search(non_dai_tokens[0]):
            informal_name = "_".join(non_dai_tokens)
        else:
            owner = non_dai_tokens[0]
            informal_name = "_".join(non_dai_tokens[1:]) if len(non_dai_tokens) > 1 else None

    return {
        "internal_project_id": internal_project_id,
        "owner": owner,
        "informal_name": informal_name,
        "genotyping_source": genotyping_source,
        "raw_header": header,
    }


def parse_sample_filename_context(csv_path: str) -> Dict[str, Any]:
    """Parse DAI project context from sample-level filename."""
    basename = os.path.basename(csv_path)
    stem = basename.rsplit(".", 1)[0]
    tokens = extract_dai_tokens(stem)
    grouped_source = "_".join(tokens)
    is_validation = bool(_VALIDATION_RE.search(stem))
    return {
        "file_name": basename,
        "genotyping_tokens": tokens,
        "genotyping_source": grouped_source,
        "is_validation": is_validation,
    }


@dataclass
class MetadataLoadResult:
    by_genotyping_source: Dict[str, Dict[str, str]]
    missing_optional_columns: List[str]
    row_count: int


@dataclass
class ProjectMappingLoadResult:
    by_project_code: Dict[str, Dict[str, str]]
    by_genotyping_source: Dict[str, List[Dict[str, str]]]
    missing_optional_columns: List[str]
    row_count: int


@dataclass
class OwnerContactsLoadResult:
    by_owner_name: Dict[str, Dict[str, str]]
    missing_optional_columns: List[str]
    row_count: int


_COLUMN_ALIASES: Dict[str, Sequence[str]] = {
    "genotyping_source": ("genotyping_source", "genotyping", "dai", "dai_source"),
    "pi_name": ("pi_name", "owner", "project_owner"),
    "pi_email": ("pi_email", "owner_email"),
    "pi_institution": ("pi_institution", "institution"),
    "pi_department": ("pi_department", "department"),
    "project_name": ("project_name", "informal_name"),
    "description": ("description", "notes"),
    "start_date": ("start_date",),
}

_MAPPING_ALIASES: Dict[str, Sequence[str]] = {
    "genotyping_source": ("genotyping_source", "genotyping", "dai", "dai_source"),
    "project_code": ("project_code", "project_header"),
    "owner_name": ("owner_name", "owner", "pi_name"),
    "project_name": ("project_name", "informal_name"),
    "description": ("description", "notes"),
    "start_date": ("start_date",),
    "is_sample_default": ("is_sample_default", "default_for_samples", "sample_default"),
}

_CONTACT_ALIASES: Dict[str, Sequence[str]] = {
    "owner_name": ("owner_name", "owner", "pi_name", "full name", "fullname"),
    "pi_name": ("pi_name", "owner_name", "owner", "full name", "fullname"),
    "pi_email": ("pi_email", "owner_email", "primary email", "email", "alternate email"),
    "pi_institution": ("pi_institution", "institution", "employer"),
    "pi_department": ("pi_department", "department", "position"),
    "pi_location": ("pi_location", "primary location", "location", "primary loca", "secondary location"),
}


def _resolve_column(df: pd.DataFrame, aliases: Iterable[str]) -> Optional[str]:
    normalized = {str(c).strip().lower(): c for c in df.columns}
    for alias in aliases:
        hit = normalized.get(alias.lower())
        if hit is not None:
            return hit
    return None


def _normalize_owner_name(name: str) -> str:
    return _safe_text(name).casefold()


def _as_bool(value: Any) -> bool:
    return _safe_text(value).lower() in {"1", "true", "yes", "y"}


def load_project_metadata(metadata_path: str) -> MetadataLoadResult:
    """Load metadata keyed by genotyping_source; required for owner/PI enrichment."""
    if not os.path.exists(metadata_path):
        raise FileNotFoundError(f"Project metadata file not found: {metadata_path}")

    df = read_matrix(metadata_path)
    key_column = _resolve_column(df, _COLUMN_ALIASES["genotyping_source"])
    if not key_column:
        raise ValueError(
            "Metadata file must include a genotyping_source column "
            "(accepted aliases: genotyping_source, genotyping, dai, dai_source)"
        )

    resolved: Dict[str, Optional[str]] = {
        logical: _resolve_column(df, aliases)
        for logical, aliases in _COLUMN_ALIASES.items()
    }

    missing_optional = [
        logical for logical, col in resolved.items()
        if logical != "genotyping_source" and not col
    ]

    by_key: Dict[str, Dict[str, str]] = {}
    for _, row in df.iterrows():
        key_value = normalize_genotyping_source(_safe_text(row[key_column]))
        if not key_value:
            continue
        entry: Dict[str, str] = {}
        for logical, column_name in resolved.items():
            if logical == "genotyping_source":
                entry[logical] = key_value
                continue
            if not column_name:
                entry[logical] = ""
                continue
            entry[logical] = _safe_text(row.get(column_name))
        by_key[key_value] = entry

    return MetadataLoadResult(
        by_genotyping_source=by_key,
        missing_optional_columns=missing_optional,
        row_count=len(df),
    )


def load_project_mapping(mapping_path: str) -> ProjectMappingLoadResult:
    """Load mapping file linking genotyping_source to canonical project_code."""
    if not os.path.exists(mapping_path):
        raise FileNotFoundError(f"Project mapping file not found: {mapping_path}")

    df = read_matrix(mapping_path)
    source_column = _resolve_column(df, _MAPPING_ALIASES["genotyping_source"])
    code_column = _resolve_column(df, _MAPPING_ALIASES["project_code"])

    if not source_column or not code_column:
        raise ValueError(
            "Project mapping file must include genotyping_source and project_code columns "
            "(aliases accepted for both)."
        )

    resolved = {logical: _resolve_column(df, aliases) for logical, aliases in _MAPPING_ALIASES.items()}
    missing_optional = [
        logical for logical, col in resolved.items()
        if logical not in {"genotyping_source", "project_code"} and not col
    ]

    by_project_code: Dict[str, Dict[str, str]] = {}
    by_source: Dict[str, List[Dict[str, str]]] = {}
    for _, row in df.iterrows():
        source_key = normalize_genotyping_source(_safe_text(row[source_column]))
        project_code = _safe_text(row[code_column])
        if not source_key or not project_code:
            continue

        owner_raw = _safe_text(row.get(resolved["owner_name"])) if resolved["owner_name"] else ""
        owner_names = [n.strip() for n in owner_raw.split(";") if n.strip()] if owner_raw else []

        mapping = {
            "genotyping_source": source_key,
            "project_code": project_code,
            "project_code_normalized": normalize_project_code(project_code),
            "owner_names": owner_names,
            "owner_name": owner_names[0] if owner_names else "",
            "project_name": _safe_text(row.get(resolved["project_name"])) if resolved["project_name"] else "",
            "description": _safe_text(row.get(resolved["description"])) if resolved["description"] else "",
            "start_date": _safe_text(row.get(resolved["start_date"])) if resolved["start_date"] else "",
            "is_sample_default": "1" if (resolved["is_sample_default"] and _as_bool(row.get(resolved["is_sample_default"]))) else "",
        }
        by_project_code[project_code] = mapping
        normalized_code = mapping["project_code_normalized"]
        if normalized_code and normalized_code not in by_project_code:
            by_project_code[normalized_code] = mapping
        by_source.setdefault(source_key, []).append(mapping)

    return ProjectMappingLoadResult(
        by_project_code=by_project_code,
        by_genotyping_source=by_source,
        missing_optional_columns=missing_optional,
        row_count=len(df),
    )


def load_owner_contacts(contacts_path: str) -> OwnerContactsLoadResult:
    """Load owner contact enrichment keyed by owner_name."""
    if not os.path.exists(contacts_path):
        raise FileNotFoundError(f"Owner contacts file not found: {contacts_path}")

    df = read_matrix(contacts_path)
    owner_column = _resolve_column(df, _CONTACT_ALIASES["owner_name"])
    if not owner_column:
        raise ValueError(
            "Owner contacts file must include owner_name (aliases: owner_name, owner, pi_name)."
        )

    resolved = {logical: _resolve_column(df, aliases) for logical, aliases in _CONTACT_ALIASES.items()}
    missing_optional = [
        logical for logical, col in resolved.items()
        if logical != "owner_name" and not col
    ]

    by_owner_name: Dict[str, Dict[str, str]] = {}
    for _, row in df.iterrows():
        owner = _safe_text(row[owner_column])
        if not owner:
            continue
        key = _normalize_owner_name(owner)
        by_owner_name[key] = {
            "owner_name": owner,
            "pi_name": _safe_text(row.get(resolved["pi_name"])) if resolved["pi_name"] else owner,
            "pi_email": _safe_text(row.get(resolved["pi_email"])) if resolved["pi_email"] else "",
            "pi_institution": _safe_text(row.get(resolved["pi_institution"])) if resolved["pi_institution"] else "",
            "pi_department": _safe_text(row.get(resolved["pi_department"])) if resolved["pi_department"] else "",
            "pi_location": _safe_text(row.get(resolved["pi_location"])) if resolved.get("pi_location") else "",
        }

    return OwnerContactsLoadResult(
        by_owner_name=by_owner_name,
        missing_optional_columns=missing_optional,
        row_count=len(df),
    )


def _build_description(raw_header: str, internal_project_id: Optional[str], genotyping_source: str, metadata_desc: str) -> str:
    parts = []
    if internal_project_id:
        parts.append(f"internal_project_id={internal_project_id}")
    if genotyping_source:
        parts.append(f"genotyping_source={genotyping_source}")
    if metadata_desc:
        parts.append(f"metadata={metadata_desc}")
    parts.append(f"raw_header={raw_header}")
    return "; ".join(parts)


def resolve_project_record(
    parsed_project: Dict[str, Optional[str]],
    mapping_row: Optional[Dict[str, str]],
    contacts_by_owner: Dict[str, Dict[str, str]],
    forced_project_code: Optional[str] = None,
) -> Dict[str, str]:
    """Build project fields from parsed header + mapping + contacts."""
    genotyping_source = parsed_project.get("genotyping_source") or ""
    mapping = mapping_row or {}

    fallback_name = (
        parsed_project.get("informal_name")
        or parsed_project.get("internal_project_id")
        or parsed_project.get("raw_header")
        or mapping.get("project_code")
        or genotyping_source
    )
    project_name = mapping.get("project_name") or fallback_name.replace("_", " ")

    owner_name = mapping.get("owner_name") or ""
    contact = contacts_by_owner.get(_normalize_owner_name(owner_name), {})
    # Keep project owner fields mapping-driven; do not persist header-derived owners.
    pi_name = contact.get("pi_name") or owner_name

    return {
        "project_code": forced_project_code or parsed_project.get("raw_header") or mapping.get("project_code") or f"GENO_{genotyping_source}",
        "project_name": project_name,
        "pi_name": pi_name,
        "pi_email": contact.get("pi_email", ""),
        "pi_institution": contact.get("pi_institution", ""),
        "pi_department": contact.get("pi_department", ""),
        "description": _build_description(
            raw_header=parsed_project.get("raw_header") or "",
            internal_project_id=parsed_project.get("internal_project_id"),
            genotyping_source=genotyping_source,
            metadata_desc=mapping.get("description", ""),
        ),
        "start_date": mapping.get("start_date", ""),
        "genotyping_source": genotyping_source,
    }


def _split_match_tokens(text: str) -> List[str]:
    """Split free text into lowercase alphanumeric tokens for fuzzy matching."""
    return [t for t in re.split(r"[^a-z0-9]+", _safe_text(text).casefold()) if t]


def _compact_match_text(text: str) -> str:
    """Compact text to lowercase alphanumeric only (e.g. 'Long-Xi' -> 'longxi')."""
    return "".join(_split_match_tokens(text))


def _score_mapping_row_for_context(row: Dict[str, str], context_text: str) -> int:
    """Score a mapping row against context text (typically a sample filename)."""
    context_tokens = set(_split_match_tokens(context_text))
    context_compact = _compact_match_text(context_text)
    if not context_tokens and not context_compact:
        return 0

    score = 0

    owner_names = row.get("owner_names") or []
    if not owner_names and row.get("owner_name"):
        owner_names = [row["owner_name"]]

    # Strong signal: owner names/tokens in file names.
    for owner in owner_names:
        owner_tokens = _split_match_tokens(owner)
        owner_compact = _compact_match_text(owner)
        if owner_compact and owner_compact in context_compact:
            score += 5
        for token in owner_tokens:
            if len(token) >= 3 and token in context_tokens:
                score += 3

    # Weak signals: project name/code fragments.
    project_name_tokens = _split_match_tokens(row.get("project_name", ""))
    for token in project_name_tokens:
        if len(token) >= 4 and token in context_tokens:
            score += 1

    project_code_compact = _compact_match_text(row.get("project_code", ""))
    if project_code_compact and project_code_compact in context_compact:
        score += 1

    return score


def pick_mapping_for_source(
    source_key: str,
    mapping_by_source: Dict[str, List[Dict[str, str]]],
    context_text: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    rows = mapping_by_source.get(source_key, [])
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]

    if context_text:
        scored = [(row, _score_mapping_row_for_context(row, context_text)) for row in rows]
        scored.sort(key=lambda item: item[1], reverse=True)
        if scored and scored[0][1] > 0:
            return scored[0][0]

    for row in rows:
        if row.get("is_sample_default") == "1":
            return row
    return rows[0]


def genotyping_sources_match(parsed_source: str, mapping_source: str) -> bool:
    """Return True when parsed and mapping genotyping sources normalize to same key."""
    parsed_key = normalize_genotyping_source(parsed_source)
    mapping_key = normalize_genotyping_source(mapping_source)
    if not parsed_key or not mapping_key:
        return False
    return parsed_key == mapping_key


def get_or_upsert_project(cursor, fields: Dict[str, str]) -> Tuple[int, bool, bool]:
    """Get existing project by project_code or create/update it.

    Returns:
      (project_id, was_created, was_updated)
    """
    project_code = fields["project_code"]
    cursor.execute("SELECT id FROM projects WHERE project_code = ?", (project_code,))
    row = cursor.fetchone()

    if row:
        project_id = int(row[0])
        cursor.execute(
            """
            UPDATE projects
            SET project_name = ?, pi_name = ?, pi_email = ?, pi_institution = ?,
                pi_department = ?, description = ?, start_date = ?
            WHERE id = ?
            """,
            (
                fields["project_name"] or "",
                fields["pi_name"] or "",
                fields["pi_email"] or "",
                fields["pi_institution"] or "",
                fields["pi_department"] or "",
                fields["description"] or "",
                fields["start_date"] or None,
                project_id,
            ),
        )
        return project_id, False, cursor.rowcount > 0

    cursor.execute(
        """
        INSERT INTO projects
        (project_code, project_name, pi_name, pi_email,
         pi_institution, pi_department, description, start_date)
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields["project_code"],
            fields["project_name"] or "",
            fields["pi_name"] or "",
            fields["pi_email"] or "",
            fields["pi_institution"] or "",
            fields["pi_department"] or "",
            fields["description"] or "",
            fields["start_date"] or None,
        ),
    )
    inserted = cursor.fetchone()
    project_id = int(inserted[0]) if inserted and inserted[0] is not None else 0

    if project_id <= 0:
        raise RuntimeError(f"Failed to resolve inserted project ID for '{project_code}'")
    return project_id, True, False


def get_or_upsert_contact(
    cursor,
    contact: Dict[str, str],
) -> Tuple[int, bool]:
    """Get or create a contact by full_name. Updates fields on re-import.

    Returns:
      (contact_id, was_created)
    """
    full_name = contact.get("pi_name") or contact.get("owner_name") or ""
    if not full_name:
        raise ValueError("Contact must have a full_name / pi_name / owner_name")

    cursor.execute("SELECT id FROM contacts WHERE full_name = ?", (full_name,))
    row = cursor.fetchone()

    if row:
        contact_id = int(row[0])
        cursor.execute(
            """
            UPDATE contacts
            SET email = ?, institution = ?, department = ?, location = ?
            WHERE id = ?
            """,
            (
                contact.get("pi_email", ""),
                contact.get("pi_institution", ""),
                contact.get("pi_department", ""),
                contact.get("pi_location", ""),
                contact_id,
            ),
        )
        return contact_id, False

    cursor.execute(
        """
        INSERT INTO contacts (full_name, email, institution, department, location)
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            full_name,
            contact.get("pi_email", ""),
            contact.get("pi_institution", ""),
            contact.get("pi_department", ""),
            contact.get("pi_location", ""),
        ),
    )
    inserted = cursor.fetchone()
    contact_id = int(inserted[0]) if inserted and inserted[0] is not None else 0

    if contact_id <= 0:
        raise RuntimeError(f"Failed to resolve inserted contact ID for '{full_name}'")
    return contact_id, True


def link_project_contacts(
    cursor,
    project_id: int,
    owner_names: List[str],
    contacts_by_owner: Dict[str, Dict[str, str]],
    role: str = "owner",
) -> Dict[str, int]:
    """Ensure project_contacts rows exist for every owner on a project.

    Returns dict of stats: created_contacts, linked_contacts, missing_contacts.
    """
    stats = {"created_contacts": 0, "linked_contacts": 0, "missing_contacts": 0}

    for owner_name in owner_names:
        key = _normalize_owner_name(owner_name)
        contact_info = contacts_by_owner.get(key)
        if not contact_info:
            contact_info = {
                "owner_name": owner_name,
                "pi_name": owner_name,
                "pi_email": "",
                "pi_institution": "",
                "pi_department": "",
            }
            stats["missing_contacts"] += 1

        contact_id, was_created = get_or_upsert_contact(cursor, contact_info)
        if was_created:
            stats["created_contacts"] += 1

        cursor.execute(
            """
            SELECT COUNT(*) FROM project_contacts
            WHERE project_id = ? AND contact_id = ?
            """,
            (project_id, contact_id),
        )
        exists = cursor.fetchone()[0] > 0

        if not exists:
            cursor.execute(
                """
                INSERT INTO project_contacts (project_id, contact_id, role)
                VALUES (?, ?, ?)
                """,
                (project_id, contact_id, role),
            )
            stats["linked_contacts"] += 1

    return stats
