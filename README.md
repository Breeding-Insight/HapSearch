# HapSearch

![HapSearch logo](static/HaploSearch_logo_main_2.png)

**Find useful microhaplotypes, understand where they occur, and connect them to the breeding programs and people who can put them to work.**

HapSearch is a web-based exploration platform for microhaplotype data in specialty crop breeding. It brings marker sequences, variants, samples, projects, and collaborator information into one searchable interface.

Microhaplotypes are short genomic regions containing multiple nearby variants observed together. Their allelic diversity and local phase information make them useful for characterizing germplasm, tracking trait-associated variation, and designing crosses.

## Why HapSearch?

Microhaplotype data is often scattered across spreadsheets, local databases, and analysis scripts. HapSearch connects these sources so breeders and researchers can answer practical questions:

- Which haplotypes occur in elite parents or breeding populations?
- Does a marker distinguish the alleles surrounding a target SNP?
- Which samples carry a rare or useful microhaplotype?
- Which projects and collaborators hold relevant germplasm?
- Where are the gaps in coverage for a crop?

## Capabilities

- Summarize microhaplotype coverage across species, chromosomes, samples, and projects
- Search and explore microhaplotypes by marker, sequence, chromosome, sample, or project
- Compare aligned sequences and visualize SNP and indel annotations
- Connect microhaplotypes to samples, breeding projects, institutions, and collaborators
- Analyze microhaplotype accumulation and sharing across projects
- Import FASTA, metadata, presence/absence, project, and variant data
- Authenticate users through ORCID with role-based administration

HapSearch is designed for breeders, quantitative geneticists, researchers, data curators, bioinformaticians, and project collaborators.

## Project overview

HapSearch is built with Python, Flask, Dash, Plotly, BioPython, and Microsoft SQL Server. The repository includes the web application, database layer, data-import tools, alignment utilities, and automated tests.

```text
alignment/   Sequence alignment and variant annotation
auth/        ORCID authentication and sessions
database/    Data access and presence/absence artifacts
pages/       Dash views and exploration workflows
scripts/     Database initialization and data imports
tests/       Automated tests
```

## Setup and development

The containerized environment uses Docker Compose with Microsoft SQL Server. Direct local development requires Python 3.13+ and ODBC Driver 18 for SQL Server. See the [SQL Server setup notes](MSSQL_SETUP.md) and [.env example](.env.example) for configuration details.

## Documentation

- [Product plan and roadmap](HaploSearch_Plan_Document.md)
- [Microsoft SQL Server setup notes](MSSQL_SETUP.md)
- [Visualization color system](design/color_palettes.md)
