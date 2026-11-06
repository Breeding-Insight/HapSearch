# HapSearch

<img src="static/brand/hapsearch-wordmark.png" alt="HapSearch" width="272">

**Find useful microhaplotypes, understand where they occur, and connect them to the breeding programs and people who can put them to work.**

HapSearch is a web-based exploration platform for microhaplotype data in specialty crop breeding, hosted by [Breeding Insight](https://breedinginsight.org/) at **[hapsearch.breedinginsight.org](https://hapsearch.breedinginsight.org/)**. It brings marker sequences, variants, samples, projects, and collaborator information into one searchable interface.

Microhaplotypes are short genomic regions containing multiple nearby variants observed together. Their allelic diversity and local phase information make them useful for characterizing germplasm, tracking trait-associated variation, and designing crosses.

## Why HapSearch?

Microhaplotype data is often scattered across spreadsheets, local databases, and analysis scripts. HapSearch connects these sources so breeders and researchers can find the microhaplotypes, samples, and collaborators relevant to their work.

## Capabilities

- **Filter by Programs**: browse breeding programs and projects, their PIs and institutions, and the microhaplotypes they hold
- **Microhaplotypes**: search by full Clone ID, chromosome, or sample, see which samples carry a microhaplotype, and save that sample list as CSV
- **Multiple Sequence Alignment**: view each microhaplotype aligned to its locus reference exactly as [BIGr](https://github.com/Breeding-Insight/BIGr) and [BIGapp](https://github.com/Breeding-Insight/BIGapp) align it, with SNP and indel annotation
- **Database Overview**: summarize coverage across species, chromosomes, samples, and projects, and export microhaplotype accumulation and sharing curves as PNG, JPEG, or SVG

## Project overview

HapSearch is built with Python, Flask, Dash, Plotly, BioPython, and SQLite. Microhaplotype alignments are computed in R (Bioconductor `pwalign`) when the database is built.

## Data

All data lives in one SQLite file built by `scripts/build_database.py` from the species data repositories listed in `data_sources.toml`, such as [alfalfa_haplotype_db](https://github.com/Breeding-Insight/alfalfa_haplotype_db). To publish new data, see:

- [Updating data and publishing a new version](docs/updating-data.md)
- [Data repository manifest example](docs/manifest.example.toml)
- [Configuration example](.env.example)

Run the automated tests with `pytest`.

## License

HapSearch is released under the [Apache License 2.0](LICENSE).
