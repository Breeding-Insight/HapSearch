-- HaploSearch Database Schema for SQLite
-- Microhaplotype Analysis Platform
--
-- Identifier/name columns use COLLATE NOCASE to keep the case-insensitive
-- matching and ordering the app relied on under SQL Server's default collation.

CREATE TABLE IF NOT EXISTS species (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    common_name TEXT COLLATE NOCASE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS chromosomes (
    id INTEGER PRIMARY KEY,
    species_id INTEGER NOT NULL REFERENCES species(id),
    chromosome_name TEXT NOT NULL COLLATE NOCASE,
    length INTEGER,
    microhaplotype_count INTEGER DEFAULT 0,
    UNIQUE (species_id, chromosome_name)
);

CREATE TABLE IF NOT EXISTS markers (
    id INTEGER PRIMARY KEY,
    marker_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
    chromosome_id INTEGER NOT NULL REFERENCES chromosomes(id),
    position_start INTEGER NOT NULL,
    position_end INTEGER NOT NULL,
    marker_type TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS microhaplotypes (
    id INTEGER PRIMARY KEY,
    marker_id INTEGER NOT NULL REFERENCES markers(id),
    haplotype_sequence TEXT NOT NULL,
    haplotype_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    frequency REAL DEFAULT 0.0,
    sample_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS variants (
    id INTEGER PRIMARY KEY,
    marker_id INTEGER NOT NULL REFERENCES markers(id),
    position INTEGER NOT NULL,
    variant_type TEXT NOT NULL CHECK (variant_type IN ('SNP', 'Indel', 'Target_SNP')),
    reference_allele TEXT NOT NULL,
    alternate_allele TEXT NOT NULL,
    frequency REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS botloci (
    id INTEGER PRIMARY KEY,
    marker_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    project_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    project_name TEXT NOT NULL COLLATE NOCASE,
    pi_name TEXT COLLATE NOCASE,
    pi_email TEXT,
    pi_institution TEXT COLLATE NOCASE,
    pi_department TEXT,
    description TEXT,
    start_date TEXT
);

CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY,
    sample_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    species_id INTEGER NOT NULL REFERENCES species(id),
    sample_type TEXT,
    collection_date TEXT,
    collection_location TEXT
);

CREATE TABLE IF NOT EXISTS microhaplotype_samples (
    microhaplotype_id INTEGER NOT NULL REFERENCES microhaplotypes(id),
    sample_id INTEGER NOT NULL REFERENCES samples(id),
    read_count INTEGER DEFAULT 0,
    PRIMARY KEY (microhaplotype_id, sample_id)
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email TEXT,
    institution TEXT COLLATE NOCASE,
    department TEXT,
    location TEXT
);

CREATE TABLE IF NOT EXISTS project_contacts (
    project_id INTEGER NOT NULL REFERENCES projects(id),
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    role TEXT DEFAULT 'owner',
    PRIMARY KEY (project_id, contact_id)
);

-- One row per imported presence/absence matrix. The matrix itself lives in
-- presence_bitmaps (one packed bit row per sample or project); this row holds
-- the shared microhaplotype axis as little-endian int64 bytes.
CREATE TABLE IF NOT EXISTS presence_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('sample', 'project')),
    species_id INTEGER,
    project_id INTEGER,
    source_path TEXT NOT NULL,
    source_sha256 TEXT,
    compression TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    microhaplotype_count INTEGER NOT NULL,
    entity_count INTEGER NOT NULL,
    presence_count INTEGER NOT NULL,
    artifact_size_bytes INTEGER,
    microhaplotype_ids BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS presence_bitmaps (
    artifact_id INTEGER NOT NULL REFERENCES presence_artifacts(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    present_count INTEGER NOT NULL,
    packed_presence BLOB NOT NULL,
    PRIMARY KEY (artifact_id, row_index)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS microhaplotype_presence_summary (
    microhaplotype_id INTEGER NOT NULL REFERENCES microhaplotypes(id),
    species_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL,
    present_count INTEGER NOT NULL,
    total_count INTEGER NOT NULL,
    frequency REAL NOT NULL,
    artifact_id INTEGER REFERENCES presence_artifacts(id),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (microhaplotype_id, species_id, entity_type)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    orcid_id TEXT NOT NULL UNIQUE,
    display_name TEXT,
    email TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_login TEXT
);

CREATE INDEX IF NOT EXISTS idx_chromosomes_species ON chromosomes(species_id);
CREATE INDEX IF NOT EXISTS idx_markers_chr ON markers(chromosome_id);
CREATE INDEX IF NOT EXISTS idx_microhap_marker ON microhaplotypes(marker_id);
CREATE INDEX IF NOT EXISTS idx_variants_marker ON variants(marker_id);
CREATE INDEX IF NOT EXISTS idx_variants_position ON variants(position);
CREATE INDEX IF NOT EXISTS idx_samples_project ON samples(project_id);
CREATE INDEX IF NOT EXISTS idx_samples_species ON samples(species_id);
CREATE INDEX IF NOT EXISTS idx_microhap_samples_sample ON microhaplotype_samples(sample_id);
CREATE INDEX IF NOT EXISTS idx_project_contacts_contact ON project_contacts(contact_id);
CREATE INDEX IF NOT EXISTS idx_presence_artifacts_entity ON presence_artifacts(entity_type, species_id, project_id);
CREATE INDEX IF NOT EXISTS idx_presence_bitmaps_entity ON presence_bitmaps(entity_id);
CREATE INDEX IF NOT EXISTS idx_presence_summary_species_entity ON microhaplotype_presence_summary(species_id, entity_type);
