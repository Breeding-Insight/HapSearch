# HapSearch

![HapSearch logo](static/HaploSearch_logo_main_2.png)

**Find useful microhaplotypes, understand where they occur, and connect them to the breeding programs and people who can put them to work.**

HapSearch is a web-based exploration platform for microhaplotype data in specialty crop breeding. It brings marker sequences, variants, samples, projects, and collaborator information into one searchable interface so breeders and researchers can move from a locus of interest to evidence they can act on.

Microhaplotypes are short genomic regions containing multiple nearby variants that are observed together. Because they can represent more allelic diversity than a single SNP while retaining local phase information, they are useful for characterizing germplasm, tracking trait-associated variation, and designing crosses.

## Why HapSearch?

Microhaplotype data is often distributed across spreadsheets, local databases, and analysis scripts. That fragmentation makes practical questions surprisingly difficult to answer:

- Which haplotypes are present in elite parents or breeding populations?
- Does a marker distinguish the alleles surrounding a target SNP?
- Which samples carry a rare or useful microhaplotype?
- Which projects and collaborators hold relevant germplasm?
- Where are the gaps in microhaplotype coverage for a crop?

HapSearch connects those questions in a single workflow. Users can begin with a species-level view, inspect the sequence evidence behind a marker, find the samples and projects associated with a microhaplotype, and identify potential collaborators for validation or germplasm exchange.

## What you can do

### Understand coverage across a species

The overview dashboard summarizes markers, microhaplotypes, samples, projects, and chromosome-level coverage. Density, accumulation, and project-sharing views help users see what is represented in the database and where more data may be valuable.

### Explore microhaplotypes

Search by marker, microhaplotype name, sequence, chromosome, sample, or project context. For each result, examine its sequence, prevalence, associated samples, breeding projects, and collaborator information.

### Inspect marker-level variation

Compare sequences in a multiple sequence alignment, view SNP and indel annotations in genomic context, and move directly between a marker and its observed microhaplotypes. HapSearch can also detect variants when annotations are not already available.

### Connect data to breeding work

HapSearch preserves the relationship between sequence variation and the projects that generated or contain it. This makes it easier to evaluate markers, locate useful germplasm, coordinate validation, and discover opportunities for cross-program collaboration.

## Who it is for

- **Breeders** evaluating markers, identifying useful alleles, and selecting material for crossing or advancement.
- **Quantitative geneticists and researchers** investigating locus-level variation and haplotype distributions.
- **Data curators and bioinformaticians** consolidating datasets and visually checking alignments, variants, and metadata.
- **Project leads and collaborators** discovering related material, expertise, and opportunities to coordinate research.

## A typical workflow

1. Select a crop species and review its data coverage.
2. Find a marker or genomic region connected to a trait of interest.
3. Inspect its aligned sequences and variant annotations.
4. Open a microhaplotype to see where it occurs.
5. Review associated samples, projects, and contacts to plan the next breeding or research step.

## Current capabilities

- Multi-species overview and database summaries
- Chromosome-level microhaplotype counts and density views
- Microhaplotype accumulation and cross-project sharing analyses
- Searchable microhaplotype and marker explorers
- Multiple sequence alignment and variant visualization
- Sample, project, institution, location, and collaborator context
- ORCID authentication with role-based administration
- Import workflows for FASTA, sample metadata, presence/absence data, projects, and variants
- Image export for overview visualizations
- Microsoft SQL Server-backed data storage
- Docker-based development and deployment options

## Project at a glance

HapSearch is a Python web application built with Flask, Dash, Plotly, BioPython, and Microsoft SQL Server. The repository contains the application, database schema and queries, data-import tools, alignment utilities, and automated tests.

```text
alignment/   Sequence alignment and variant annotation
auth/        ORCID authentication and sessions
database/    Data access and presence/absence artifacts
pages/       Dash views and exploration workflows
scripts/     Database initialization and data imports
tests/       Automated tests
```

## Setup and development

The supported containerized environment uses Docker Compose with Microsoft SQL Server. Direct local development requires Python 3.13+ and ODBC Driver 18 for SQL Server. See the [SQL Server setup notes](MSSQL_SETUP.md) and [.env example](.env.example) for configuration details.

## Project documentation

- [Product plan and roadmap](HaploSearch_Plan_Document.md)
- [Microsoft SQL Server setup notes](MSSQL_SETUP.md)
- [Visualization color system](design/color_palettes.md)
