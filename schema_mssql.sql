-- HaploSearch Database Schema for Microsoft SQL Server
-- Microhaplotype Analysis Platform

CREATE TABLE species (
    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
    name NVARCHAR(255) NOT NULL UNIQUE,
    common_name NVARCHAR(255),
    description NVARCHAR(MAX)
);

CREATE TABLE chromosomes (
    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
    species_id INT NOT NULL,
    chromosome_name NVARCHAR(255) NOT NULL,
    length INT,
    microhaplotype_count INT DEFAULT 0,
    CONSTRAINT FK_chromosomes_species FOREIGN KEY (species_id) REFERENCES species(id),
    CONSTRAINT UQ_chromosomes_species_name UNIQUE (species_id, chromosome_name)
);

CREATE TABLE markers (
    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
    marker_id NVARCHAR(255) NOT NULL UNIQUE,
    chromosome_id INT NOT NULL,
    position_start INT NOT NULL,
    position_end INT NOT NULL,
    marker_type NVARCHAR(50),
    description NVARCHAR(MAX),
    CONSTRAINT FK_markers_chromosomes FOREIGN KEY (chromosome_id) REFERENCES chromosomes(id)
);

CREATE TABLE microhaplotypes (
    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
    marker_id INT NOT NULL,
    haplotype_sequence NVARCHAR(MAX) NOT NULL,
    haplotype_name NVARCHAR(255) NOT NULL UNIQUE,
    frequency FLOAT DEFAULT 0.0,
    sample_count INT DEFAULT 0,
    CONSTRAINT FK_microhaplotypes_markers FOREIGN KEY (marker_id) REFERENCES markers(id)
);

CREATE TABLE variants (
    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
    marker_id INT NOT NULL,
    position INT NOT NULL,
    variant_type NVARCHAR(50) NOT NULL,
    reference_allele NVARCHAR(MAX) NOT NULL,
    alternate_allele NVARCHAR(MAX) NOT NULL,
    frequency FLOAT DEFAULT 0.0,
    CONSTRAINT FK_variants_markers FOREIGN KEY (marker_id) REFERENCES markers(id),
    CONSTRAINT CK_variants_type CHECK (variant_type IN ('SNP', 'Indel', 'Target_SNP'))
);

CREATE TABLE botloci (
    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
    marker_id NVARCHAR(255) NOT NULL UNIQUE,
    created_at DATETIME DEFAULT GETDATE()
);

CREATE TABLE projects (
    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
    project_code NVARCHAR(255) NOT NULL UNIQUE,
    project_name NVARCHAR(255) NOT NULL,
    pi_name NVARCHAR(255),
    pi_email NVARCHAR(255),
    pi_institution NVARCHAR(255),
    pi_department NVARCHAR(255),
    description NVARCHAR(MAX),
    start_date DATE
);

CREATE TABLE samples (
    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
    sample_code NVARCHAR(255) NOT NULL UNIQUE,
    project_id INT NOT NULL,
    species_id INT NOT NULL,
    sample_type NVARCHAR(50),
    collection_date DATE,
    collection_location NVARCHAR(255),
    CONSTRAINT FK_samples_projects FOREIGN KEY (project_id) REFERENCES projects(id),
    CONSTRAINT FK_samples_species FOREIGN KEY (species_id) REFERENCES species(id)
);

CREATE TABLE microhaplotype_samples (
    microhaplotype_id INT NOT NULL,
    sample_id INT NOT NULL,
    read_count INT DEFAULT 0,
    PRIMARY KEY (microhaplotype_id, sample_id),
    CONSTRAINT FK_microhaplotype_samples_microhaplotypes FOREIGN KEY (microhaplotype_id) REFERENCES microhaplotypes(id),
    CONSTRAINT FK_microhaplotype_samples_samples FOREIGN KEY (sample_id) REFERENCES samples(id)
);

CREATE TABLE allele_sample_presence (
    microhaplotype_id INT NOT NULL,
    sample_id INT NOT NULL,
    PRIMARY KEY (microhaplotype_id, sample_id),
    CONSTRAINT FK_allele_sample_presence_microhaplotypes FOREIGN KEY (microhaplotype_id) REFERENCES microhaplotypes(id),
    CONSTRAINT FK_allele_sample_presence_samples FOREIGN KEY (sample_id) REFERENCES samples(id)
);

CREATE TABLE allele_project_presence (
    microhaplotype_id INT NOT NULL,
    project_id INT NOT NULL,
    PRIMARY KEY (microhaplotype_id, project_id),
    CONSTRAINT FK_allele_project_presence_microhaplotypes FOREIGN KEY (microhaplotype_id) REFERENCES microhaplotypes(id),
    CONSTRAINT FK_allele_project_presence_projects FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE contacts (
    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
    full_name NVARCHAR(255) NOT NULL UNIQUE,
    email NVARCHAR(255),
    institution NVARCHAR(255),
    department NVARCHAR(255),
    location NVARCHAR(255)
);

CREATE TABLE project_contacts (
    project_id INT NOT NULL,
    contact_id INT NOT NULL,
    role NVARCHAR(50) DEFAULT 'owner',
    PRIMARY KEY (project_id, contact_id),
    CONSTRAINT FK_project_contacts_projects FOREIGN KEY (project_id) REFERENCES projects(id),
    CONSTRAINT FK_project_contacts_contacts FOREIGN KEY (contact_id) REFERENCES contacts(id)
);

CREATE TABLE users (
    id INT NOT NULL IDENTITY(1,1) PRIMARY KEY,
    orcid_id NVARCHAR(255) NOT NULL UNIQUE,
    display_name NVARCHAR(255),
    email NVARCHAR(255),
    role NVARCHAR(10) NOT NULL DEFAULT 'user',
    is_active INT DEFAULT 1,
    created_at DATETIME DEFAULT GETDATE(),
    last_login DATETIME,
    CONSTRAINT CK_users_role CHECK (role IN ('admin', 'user'))
);

CREATE INDEX idx_chromosomes_species ON chromosomes(species_id);
CREATE INDEX idx_markers_id ON markers(marker_id);
CREATE INDEX idx_markers_chr ON markers(chromosome_id);
CREATE INDEX idx_microhap_marker ON microhaplotypes(marker_id);
CREATE INDEX idx_microhap_name ON microhaplotypes(haplotype_name);
CREATE INDEX idx_variants_marker ON variants(marker_id);
CREATE INDEX idx_variants_position ON variants(position);
CREATE INDEX idx_botloci_marker_id ON botloci(marker_id);
CREATE INDEX idx_samples_project ON samples(project_id);
CREATE INDEX idx_samples_species ON samples(species_id);
CREATE INDEX idx_microhap_samples_hap ON microhaplotype_samples(microhaplotype_id);
CREATE INDEX idx_microhap_samples_sample ON microhaplotype_samples(sample_id);
CREATE INDEX idx_allele_presence_sample ON allele_sample_presence(sample_id);
CREATE INDEX idx_allele_project_presence_project ON allele_project_presence(project_id);
CREATE INDEX idx_contacts_full_name ON contacts(full_name);
CREATE INDEX idx_project_contacts_project ON project_contacts(project_id);
CREATE INDEX idx_project_contacts_contact ON project_contacts(contact_id);
CREATE INDEX idx_users_orcid ON users(orcid_id);
