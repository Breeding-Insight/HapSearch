# HaploSearch Plan Document

## Why

Specialty crop breeding programs at Breeding Insight, USDA ARS, and partner institutions generate microhaplotype data across multiple projects and research groups, but this information resides in isolated spreadsheets, local databases, and ad-hoc scripts, making it difficult for breeders to identify which haplotypes are present in their elite parents, which markers tag target SNPs for traits of interest, or which collaborators hold germplasm carrying specific alleles. HaploSearch addresses this fragmentation by providing a unified web-based platform that centralizes microhaplotype, variant, and sample metadata in a single interface, connecting sequence-level information directly to breeding projects and samples while integrating visualization tools for multiple sequence alignments, variant annotation, and haplotype frequency analysis with project and PI tracking to support both individual breeding decisions and collaborative research.

## User Profiles

### Breeding Insight Scientist

- Data curators and platform developers supporting multiple specialty crop breeding programs
- Import and validate microhaplotype data from various sources using import scripts
- Ensure data quality through visual inspection of alignments and variant calls in Marker Explorer
- Maintain centralized database serving all participating programs
- Monitor Overview dashboard to assess data coverage and identify gaps
- Use platform as training tool when onboarding new breeding programs

### Breeder

- Primary end users making practical breeding decisions for specialty crops
- Identify which haplotypes are present in elite parents and breeding populations
- Evaluate whether markers effectively tag target SNPs for traits of interest
- Determine which markers are ready for deployment in routine breeding workflows
- Start with Overview dashboard to assess microhaplotype data coverage for their crop
- Use Marker Explorer to inspect markers linked to traits, confirm target SNP support via MSA visualization
- Navigate to Haplotype Explorer to see haplotypes in elite parents, checks, and key families
- Make informed selections and prioritize lines to advance in breeding programs

### Collaborators

- Principal Investigators, project managers, and researchers from ARS, universities, and partner institutions
- Discover which projects and researchers have samples carrying haplotypes of interest
- Facilitate germplasm exchange, collaborative validation trials, and coordinated breeding efforts
- Use Haplotype Explorer's project and PI tracking to identify collaborators with relevant material
- View contact information and coordinate seed or cuttings exchange
- Track own project's contributions and monitor haplotype frequencies across sample collections
- Identify opportunities for joint publications or shared validation studies
- Gain visibility into how their contributed data is used across the breeding community

## Current Features

### Overview Dashboard

Entry point for data exploration providing high-level statistics and visualizations for selected species.

- Species selection dropdown with global state management
- Chromosome microhaplotype counts bar chart visualization
- Allele density plots across chromosome positions (area charts by chromosome)
- Project and Principal Investigator (PI) statistics cards
- Database statistics header (species, markers, haplotypes, samples counts)

**Intended Goal/Outcome**: Users quickly assess data distribution and identify areas of interest.

### Marker Explorer

Split-view interface for searching, browsing, and examining genetic markers with comprehensive sequence analysis.

- Left panel: Searchable marker list with chromosome filter and marker ID search
- Right panel: Detailed marker view with genomic position and haplotype count
- Multiple Sequence Alignment (MSA) visualization with color-coded nucleotides (A, G, C, T, gaps)
- Variant annotation overlay (SNPs, Indels, Target SNPs) with visual markers
- Toggle between original unaligned and CLUSTAL Omega-aligned sequences
- Automatic variant detection from sequences when variants not in database
- Genomic position mapping for aligned sequences
- Cross-tab navigation to Haplotype Explorer via haplotype links
- Minimizable left panel for expanded detail view

**Intended Goal/Outcome**: Researchers identify and analyze genetic markers with variant visualization to understand sequence variation patterns.

### Haplotype Explorer

Multi-criteria search interface for discovering haplotypes and connecting to associated samples and projects.

- Search by marker ID, haplotype name, or sequence
- Split-view with searchable list (left) and detailed view (right)
- Haplotype detail display: sequence, sample count, frequency statistics
- Associated projects and PI contact information with email links
- Expandable samples table with filtering and sorting
- Expandable project cards showing PI details and project statistics
- Cross-tab navigation to Marker Explorer
- Minimizable left panel

**Intended Goal/Outcome**: Users find haplotypes, understand their distribution, and connect with researchers for collaboration.

### Sequence Alignment

CLUSTAL Omega integration for accurate multiple sequence alignment and variant detection.

- Automatic alignment when markers are selected in Marker Explorer
- Variant annotation from aligned sequences (SNPs, indels, transitions, transversions)
- Genomic position mapping accounting for gaps in aligned sequences
- Visualization of gaps and indels in MSA heatmap
- Support for target SNP identification (single difference between Ref and Alt sequences)

**Intended Goal/Outcome**: Variants are correctly identified and visualized in genomic context, improving variant detection accuracy.

### Data Management

Microsoft SQL Server database with comprehensive schema and query functions supporting all application features.

- Schema: species, chromosomes, markers, microhaplotypes, variants, projects, samples, associations
- Query functions for pagination, filtering, and statistics aggregation
- Indexed tables for performance on large datasets
- Support for flexible sample metadata (key-value storage)

**Intended Goal/Outcome**: Efficient storage and retrieval of large-scale genetic data with support for complex queries.

### Data Import

Command-line scripts for importing and initializing data from various sources.

- `init_database.py`: Initialize database schema
- `import_fasta.py`: Import FASTA sequence files with haplotype extraction
- `import_samples.py`: Import sample metadata with project associations
- `import_variants.py`: Import variant annotations (SNPs, Indels, Target SNPs)
- `detect_variants.py`: Auto-detect variants from sequences

**Intended Goal/Outcome**: Efficient data loading workflows with maintained data integrity during imports.

## MVP Features

### Core Features (Already Implemented)

- Multi-species support with database statistics
- Marker search and exploration with MSA visualization
- Haplotype search with sample and project associations
- Basic data import scripts for FASTA, samples, and variants

### MVP Enhancements Needed

**Performance Optimization**: Database query caching, optimized pagination, loading indicators, and lazy loading for visualizations.

**Data Validation**: Enhanced input validation, user-friendly error messages, data integrity checks, and graceful handling of missing data.

**User Experience**: Tooltips and help text, keyboard shortcuts, improved mobile responsiveness, and better visual feedback.

**Documentation**: User guides, API documentation, deployment guides, and troubleshooting resources.

**Basic Export**: Export marker data to CSV, haplotype sequences to FASTA, and sample lists with metadata.

## Future Version Roadmap

### Version 1.1 (Near-term)

**Features:**
- Enhanced filtering and search with multiple criteria combinations, saved queries, and search history
- Export functionality (CSV, FASTA, customizable reports, batch operations)
- User authentication and access control (basic accounts, role-based permissions, access logging)
- Performance improvements (database optimization, query caching, background processing)
- Additional visualizations (interactive chromosome browser, variant frequency plots, sample distribution maps)

**Goals**: Improve usability, support data sharing and collaboration, optimize for production use.

### Version 1.2 (Medium-term)

**Features:**
- Advanced statistical analysis (haplotype frequency calculations, linkage disequilibrium, population genetics statistics)
- Comparative analysis across species (cross-species marker comparison, phylogenetic visualization, synteny analysis)
- Batch operations and bulk exports (multi-marker export, bulk variant annotation, automated reports)
- API endpoints for programmatic access (RESTful API, Python client library, integration examples)
- Integration with external databases (NCBI GenBank, Ensembl, UniProt)

**Goals**: Enable advanced research workflows, support automation and integration, expand analytical capabilities.

### Version 2.0 (Long-term)

**Features:**
- Machine learning for variant prediction (variant effect prediction, haplotype classification, anomaly detection)
- Real-time collaboration (shared annotations, collaborative filtering, comment threads)
- Advanced visualization (3D structures, network graphs, interactive genome browsers)
- Mobile-responsive design (full mobile experience, touch-optimized, offline access)
- Cloud deployment options (AWS/Azure/GCP guides, auto-scaling, managed services)

**Goals**: Position as comprehensive research platform, support cutting-edge research methods, enable broader accessibility.

## Technical Stack

**Current Stack**: Python 3.13+ with Dash web framework, Microsoft SQL Server, BioPython for bioinformatics, CLUSTAL Omega/MUSCLE for sequence alignment, Plotly for visualization, and Docker for deployment.

**Future Considerations**: PostgreSQL/MySQL for larger datasets, Redis for caching, FastAPI for REST APIs, cloud services for hosting, Kubernetes for scalable deployments.

## Distribution Model

**Current Distribution**: Open-source project via GitHub, Docker container for easy deployment, direct installation with Python, suitable for research institutions and labs.

**Future Options**: Academic/research distribution partnerships, commercial licensing options, cloud marketplace listings, research software registries.

## Usage Patterns

### Internal Usage

**Breeding Program Exploration (Breeding Insight, ARS, and partners)**: Breeders and project scientists use the Overview dashboard to filter by species and quickly see which chromosomes and markers currently have microhaplotype coverage for their crop. This helps prioritize which target regions to genotype next and which programs already have usable data.

**Marker and Haplotype Evaluation for Trait Deployment**: Using the Marker Explorer and its MSA view, breeders and quantitative geneticists inspect specific microhaplotype markers to confirm that target SNPs are well supported, nearby variants are understood, and alleles are distinguishable in their breeding material. From there, they follow links into the Haplotype Explorer to see which haplotypes occur in elite parents, checks, and key families.

**Cross-project and PI-level tracking**: The Haplotype Explorer's sample and project panels let ARS and university collaborators see which projects (and which PIs) have samples carrying a haplotype of interest. This supports decisions about sharing plant material, aligning phenotyping across programs, or validating markers in new backgrounds.

**Data Quality and Platform Readiness Checks**: Bioinformatics staff and data curators use the alignment tools and variant-detection outputs to spot questionable haplotypes or mis-annotated variants before recommending a marker panel for routine breeding use. Import scripts are used to bring in new project, sample, and variant datasets and then visually verify them via the dashboards.

### External/User Usage

**Breeder-oriented exploration**: Select crop species -> Use the Overview dashboard to see chromosomes and markers with microhaplotype data -> Open Marker Explorer for loci linked to traits of interest -> Inspect alignments and variant calls -> Jump into Haplotype Explorer to see which selections and breeding lines carry the desired haplotype.

**Collaboration and germplasm discovery**: Starting from a haplotype or marker of interest, users use the Haplotype Explorer to identify which projects and PIs hold relevant material, then follow the built-in contact links to coordinate seed/cuttings exchange, shared validation trials, or joint publications.

**Operational data loading**: Data managers prepare FASTA, sample, and variant files from existing pipelines, use the import scripts to load them into HaploSearch, then rely on the Overview dashboard, Marker Explorer, and alignment tools as a visual QA step before breeders start using the data in decision-making.

**Method development and training**: Breeding Insight and ARS scientists use the MSA and variant-annotation views as teaching tools when working with new programs, demonstrating how microhaplotypes behave around target SNPs and how different haplotypes map onto real breeding germplasm.

## Feature Function Goals and Outcomes

**Overview Dashboard**: Provide comprehensive data overview. Users quickly understand available data and navigate to areas of interest.

**Marker Explorer**: Enable detailed marker analysis. Researchers identify and analyze genetic markers with variant visualization.

**Haplotype Explorer**: Facilitate haplotype discovery and collaboration. Users find haplotypes, understand distribution, and connect with researchers.

**Sequence Alignment**: Provide accurate sequence comparison. Variants are correctly identified and visualized in genomic context.

**Data Management**: Support large-scale data operations. Efficient storage, retrieval, and import of genetic datasets.
