# Presence/Absence Storage and Import Assessment

## Executive Summary

The presence/absence import path now stores the large boolean matrix as compressed filesystem artifacts, not as one SQL Server row per present cell. SQL Server remains the system of record for metadata, artifact manifests, and compact summary rows used by the UI.

There are two separate problems to solve:

1. SQL Server operations: under `FULL` recovery, any large rowstore insert/delete workload is logged and constrained by the 2 GB log cap on the current servers.
2. Data model scale: one row per `(microhaplotype_id, sample_id)` presence edge will eventually become too large if the project expects many orders of magnitude more samples.

The recommended path is:

1. Keep presence/absence imports on the artifact-backed path.
2. Store both orientations for full UI parity: allele-to-sample/project and sample/project-to-allele.
3. Maintain compact SQL summaries for frequency, counts, and artifact lookup.
4. Avoid reintroducing permanent row-per-presence SQL tables unless a future feature proves it needs them.

## Current Implementation

The SQL Server schema has two presence-artifact tables:

- `presence_artifacts`: one manifest row per compressed artifact file.
- `microhaplotype_presence_summary`: one compact row per microhaplotype/species/entity type with present count, total count, frequency, and artifact ID.

The compressed files live under `/srv/hapsearch/production/presence_artifacts` in production and `/srv/hapsearch/development/presence_artifacts` in development by default, or `PRESENCE_ARTIFACT_DIR` when configured.

The sample importer:

- reads the whole CSV into a pandas `DataFrame`;
- resolves allele names to `microhaplotype_id`;
- resolves or creates samples;
- builds a presence-pair list in memory;
- writes an allele-to-sample compressed bitmap;
- writes a sample-to-allele compressed bitmap;
- records artifact metadata and compact summary rows in SQL Server.

The project importer follows the same pattern for allele-to-project and project-to-allele artifacts.

## Why the Log Fills

Microsoft documents that every SQL Server database has a transaction log recording transactions and database modifications. In `FULL` recovery, log truncation happens after a transaction log backup, not merely because a transaction commits or a checkpoint occurs. Microsoft also documents that if `LOG_BACKUP` is the reuse wait reason, regular transaction log backups are required.

Relevant Microsoft references:

- Transaction log truncation and `FULL` recovery: https://learn.microsoft.com/en-us/sql/relational-databases/logs/the-transaction-log-sql-server
- Error 9002/full log troubleshooting: https://learn.microsoft.com/en-us/sql/relational-databases/logs/troubleshoot-a-full-transaction-log-sql-server-error-9002
- Minimal logging prerequisites for bulk import: https://learn.microsoft.com/en-us/sql/relational-databases/import-export/prerequisites-for-minimal-logging-in-bulk-import

Important implications for HaploSearch:

- The previous rowstore design could fill the 2 GB log cap because every presence edge was inserted into SQL Server.
- The current artifact design avoids that raw matrix write. SQL Server logs only metadata, sample/project rows, artifact manifests, and compact summary updates.
- Frequency browsing is served by `microhaplotypes` and `microhaplotype_presence_summary`, not by scanning a large edge table.
- Detail and filter views read compressed artifacts on demand.

## Immediate Production Assessment

Run these read-only diagnostics on the target SQL Server before changing code:

```sql
SELECT
    name,
    recovery_model_desc,
    log_reuse_wait_desc
FROM sys.databases
WHERE name = DB_NAME();
```

```sql
SELECT
    total_log_size_mb = total_log_size_in_bytes / 1024.0 / 1024.0,
    used_log_space_mb = used_log_space_in_bytes / 1024.0 / 1024.0,
    used_log_space_in_percent,
    log_space_since_last_backup_mb =
        log_space_in_bytes_since_last_backup / 1024.0 / 1024.0
FROM sys.dm_db_log_space_usage;
```

```sql
SELECT TOP (20)
    bs.database_name,
    bs.type,
    backup_type =
        CASE bs.type
            WHEN 'D' THEN 'Full'
            WHEN 'I' THEN 'Differential'
            WHEN 'L' THEN 'Transaction Log'
            ELSE bs.type
        END,
    bs.backup_start_date,
    bs.backup_finish_date,
    backup_size_mb = bs.backup_size / 1024.0 / 1024.0,
    compressed_backup_size_mb = bs.compressed_backup_size / 1024.0 / 1024.0
FROM msdb.dbo.backupset bs
WHERE bs.database_name = DB_NAME()
ORDER BY bs.backup_start_date DESC;
```

Expected finding if the reported behavior is the root cause:

- `recovery_model_desc = FULL`
- `log_reuse_wait_desc = LOG_BACKUP`
- no frequent `L` transaction log backups

Actual BRIN_01 findings reported on 2026-06-22:

- `BRIN_01` is in `FULL` recovery.
- `log_reuse_wait_desc = NOTHING`, so SQL Server is not currently blocked from reusing log space by a missing log backup.
- The account cannot query `sys.dm_db_log_space_usage` because it lacks `VIEW SERVER STATE`.
- Backup history shows daily full backups around 11:59 and several transaction log backups per day. Recent log backups are tiny when idle, around `0.077 MB` uncompressed.
- Production log settings:
  - `LogFileSize = 512 MB`
  - `LogFileGrowth = 128 MB`
  - `LogMaxSize = 2048 MB`
  - `Recovery Model = FULL`
- Development log settings:
  - `LogFileSize = 256 MB`
  - `LogFileGrowth = 128 MB`
  - `LogMaxSize = 2048 MB`
  - `Recovery Model = FULL`

Interpretation:

- The weekly-reset hypothesis is probably incomplete. This database does have transaction log backups.
- The import can still fill the log if one transaction is larger than the available log space, because the active portion of the log cannot be truncated until that transaction commits.
- The current importer has exactly that risk: staging rows are committed in chunks, but the final target-table insert and stale delete are each one large transaction.
- The hard `2048 MB` maximum log size is small for multi-million-row, fully logged imports. The effective safe transaction size is much smaller than 2 GB because SQL Server also logs index maintenance, allocation changes, deletes, constraint checks, frequency updates, and any concurrent database activity.
- With 128 MB autogrowth increments, a large import may also spend time repeatedly growing the log. If growth is slow or quota-bound, this can surface as log-full behavior even before the application-level import is complete.
- Without `sys.dm_db_log_space_usage`, ask the DBA whether imports hit the 2048 MB max size, how much of the log is active during the failed transaction, and whether autogrowth events are succeeding.

## Option A: DBA/Operations Fix

If point-in-time recovery matters, keep `FULL` recovery but configure frequent transaction log backups, for example every 5-15 minutes during import windows. Also size the log file for the largest expected import burst instead of relying on many autogrowth events.

Pros:

- No application behavior changes.
- Preserves point-in-time recovery.
- Likely fixes the immediate "wait a week" problem.

Cons:

- Does not reduce total write volume.
- Log backups must be retained and monitored.
- A single huge transaction can still fill the active log before a backup can truncate it.

If point-in-time recovery is not required for this database, switching to `SIMPLE` recovery would allow log reuse after checkpoints, but this changes restore guarantees and should be a DBA/product decision.

For controlled one-time bulk loading, another operational pattern is:

1. take a log backup;
2. switch temporarily from `FULL` to `BULK_LOGGED`;
3. perform eligible bulk loads;
4. switch back to `FULL`;
5. take a full/log backup as required by the backup strategy.

This only helps if the load method and table/index state meet SQL Server's minimal logging prerequisites. The current pyodbc `executemany` plus non-empty primary-key rowstore table should not be assumed to receive minimal logging.

## Project-Level Presence

Project-level presence is much smaller than sample-level presence because the entity dimension is projects rather than samples. If many workflows only need "which project contains this microhaplotype," then project-oriented compressed artifacts should be the first-class browse path.

Recommended project-level strategy:

- Store project-level matrices as compressed project artifacts plus SQL summaries.
- Import project-level matrices first when available because they are naturally compact.
- Derive project panels from sample artifacts when only sample-level matrices are available.

This reduces sample-level write volume only if the product can accept project-level answers for some workflows.

## Option D: Compressed Presence Bitmaps

For long-term scale, store each microhaplotype's presence across samples/projects as a compressed bitmap instead of one row per presence edge.

Possible schema:

```sql
CREATE TABLE presence_sample_bitmap (
    microhaplotype_id INT NOT NULL,
    species_id INT NOT NULL,
    sample_universe_version INT NOT NULL,
    present_count INT NOT NULL,
    bitmap VARBINARY(MAX) NOT NULL,
    compression NVARCHAR(32) NOT NULL,
    updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    PRIMARY KEY (microhaplotype_id, species_id, sample_universe_version)
);

CREATE TABLE sample_universe (
    id INT IDENTITY(1,1) PRIMARY KEY,
    species_id INT NOT NULL,
    version INT NOT NULL,
    sample_count INT NOT NULL,
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    UNIQUE (species_id, version)
);

CREATE TABLE sample_universe_member (
    universe_id INT NOT NULL,
    sample_id INT NOT NULL,
    ordinal INT NOT NULL,
    PRIMARY KEY (universe_id, sample_id),
    UNIQUE (universe_id, ordinal)
);
```

Read patterns:

- Frequency becomes `present_count / sample_count`, no join over edge rows.
- Allele detail can decompress one bitmap and resolve ordinals to sample IDs.
- Sample search uses a secondary sample-oriented bitmap artifact, so the UI can answer both allele-to-samples and sample-to-alleles without a relational row per presence edge.

Pros:

- Orders-of-magnitude fewer SQL rows.
- Smaller indexes.
- Lower log volume if updates are batch-oriented.
- Frequency queries become cheap.

Cons:

- More application logic.
- Harder ad hoc SQL.
- Updating a bitmap when the sample universe changes requires versioning or append-friendly chunks.

This is the strongest long-term storage option if sample-level presence must scale dramatically.

## Option E: Columnstore/Analytic Edge Table

SQL Server clustered columnstore can compress large fact tables well and is designed for analytic scans. A presence fact table shaped as `(microhaplotype_id, sample_id, project_id, species_id, import_batch_id)` could use columnstore for storage and query efficiency.

Pros:

- Keeps SQL relational.
- Good compression for large fact tables.
- Good for aggregate/browse queries.

Cons:

- Point lookups and singleton detail views may need supporting rowstore indexes.
- Deletes/updates are not ideal; append-and-supersede is better.
- Requires careful load pattern and SQL Server edition/version validation.

This is a good middle ground if the team wants to stay SQL-native and avoid custom bitmap encoding.

## Option F: External Analytical Store

Presence matrices are naturally sparse/analytic data. Alternatives include Parquet files, DuckDB, Spark, or object storage with metadata in SQL Server.

Pattern:

- SQL Server stores projects, samples, owners, markers, microhaplotypes, import batches, and file manifests.
- Presence data is stored as compressed Parquet or sparse matrix files partitioned by species/project/import batch.
- The app reads derived summaries from SQL Server and uses an analytic engine for detail expansion.

Pros:

- Very compact.
- Bulk loads avoid SQL Server transaction log pressure for raw matrix data.
- Better fit for massive matrix-scale analytics.

Cons:

- Larger architecture change.
- More deployment complexity.
- Harder to make all UI interactions pure SQL Server queries.

This becomes attractive if the expected scale is beyond what SQL Server rowstore/columnstore should own operationally.

## Long-Term Recommendation for the UFIT/VPN VM Constraint

Given the reported deployment constraints:

- the app runs on a VM behind the VPN;
- SQL Server access is available, but database administration is limited;
- both dev and production logs are capped at `2048 MB`;
- the current UI needs allele search, frequency filtering, allele detail, sample lists, project lists, and species summaries;
- alfalfa is only the first/small dataset, with more species expected;

the best long-term architecture is a hybrid model:

1. Keep SQL Server as the system of record for metadata.
   - species, chromosomes, markers, microhaplotypes
   - projects, contacts, samples
   - import batches and file manifests
   - compact frequency/sample/project summaries used by the UI

2. Move the massive sample-level presence matrix out of row-per-presence SQL storage.
   - Store immutable compressed presence artifacts on the VM filesystem, or in a UFIT-approved shared storage location if one exists.
   - Use one artifact per species/import batch or per species/chromosome shard.
   - Store checksums, paths, matrix dimensions, and schema versions in SQL Server.

3. Keep compact SQL summary tables for UI speed.
   - `microhaplotype_presence_summary`: one row per microhaplotype/species with `present_sample_count`, `total_sample_count`, `frequency`.
   - `presence_artifacts`: one row per compressed artifact, including both allele-oriented and sample/project-oriented lookup files.
   - Optional `sample_presence_summary`: one row per sample/project/species for counts and quick sample/project pages.

4. Expand sample-level details on demand.
   - When a user opens one allele, read/decompress that allele's presence vector and resolve sample IDs through SQL.
   - For common alleles, cache the expanded sample list in a temporary/cache table or application cache.

This preserves current UI functionality while avoiding the worst SQL Server transaction-log path: inserting millions of individual sample-presence rows.

### Preferred Artifact Format

Use compressed bitmaps or Parquet, not raw CSV.

Best fit for current UI:

- compressed bitmap per microhaplotype, keyed by a stable sample-universe ordinal;
- plus SQL tables mapping `sample_id <-> ordinal` for each species/sample-universe version.

Good alternatives:

- Parquet with columns like `microhaplotype_id`, `sample_id`, `project_id`, `species_id`, partitioned by species/chromosome/import batch;
- DuckDB locally on the VM to query Parquet artifacts for detail expansion.

If minimizing moving parts matters most, compressed bitmap files are likely better than adding a separate analytical engine. If ad hoc analytics will become important, Parquet plus DuckDB is attractive.

## Efficiency Estimates

These estimates are approximate and should be validated with one representative multi-file dataset. They are intended to compare order-of-magnitude behavior, not predict exact SQL Server internals.

Definitions:

- `A` = number of microhaplotypes/alleles
- `S` = number of samples
- `P` = number of present cells
- `D` = density = `P / (A * S)`

### Current Rowstore Presence Table

Current storage unit:

- one SQL row per present `(microhaplotype_id, sample_id)` pair;
- clustered primary key on both IDs;
- optional secondary lookup index by `sample_id`;
- fully logged inserts/deletes under `FULL` recovery.

Approximate storage/logging:

- logical payload is only 8 bytes per pair (`INT + INT`);
- practical table/index storage is often closer to 20-50+ bytes per pair after row overhead, B-tree pages, and indexes;
- logged bytes per inserted pair can be similar or higher, and the current staging flow can log the data more than once;
- deletes and index rebuilds add more log.

Rule of thumb:

- `10 million` presence pairs can easily mean hundreds of MB to multiple GB of data/log activity once staging, target insert, indexes, and deletes are included.
- With a hard `2048 MB` log cap, one unchunked target insert can fail even when the input CSV is only around `1 GB`.

### Batched Rowstore Import

Storage reduction:

- `0x`; table size is unchanged.

Peak log reduction:

- strong reduction in peak active log, because each target insert/delete commits separately.
- if current import attempts `P` rows in one transaction and batching inserts `B` rows per transaction, peak insert log can drop roughly by `P / B`.

Example:

- if a file builds `10 million` presence pairs and target batches are `100,000` rows, peak insert transaction size is about `100x` smaller than the current unchunked insert.
- total log generated across the whole file remains broadly similar.

Use this as the required short-term fix, not as the final scale strategy.

### SQL Server Columnstore Fact Table

Storage reduction:

- often `4x-10x` compared with rowstore for large repetitive integer fact tables, sometimes better depending on sort/order and cardinality.

Logging reduction:

- can improve if the workflow is append-oriented and loaded in well-sized batches;
- not guaranteed under the current update/delete-style importer;
- deletes and upserts are less natural than append-and-supersede.

UI impact:

- aggregate/frequency queries can be good;
- allele detail and sample lookup may still need rowstore helper indexes or summary tables.

This is a reasonable SQL-native option, but it still lives inside the database log cap.

### Compressed Bitmap Artifacts

Uncompressed bitmap size:

- `A * S / 8` bytes.

Example:

- `100,000` alleles x `10,000` samples = `1,000,000,000` cells.
- Uncompressed bitmap size = about `125 MB`.
- A row-per-presence table at 10% density has `100,000,000` presence rows. At even 30 bytes/row, that is about `3 GB` before considering all logging and maintenance overhead.

Storage reduction compared with row-per-presence:

- at `10%` density: commonly `20x+` smaller before compression;
- at `1%` density: rowstore becomes less terrible, but compressed sparse bitmaps can still be very efficient;
- at high density, bitmaps become dramatically better because rowstore grows with present cells while bitmap grows with total cells.

Logging reduction:

- if artifacts are stored on the VM filesystem and SQL stores only metadata/summaries, raw matrix logging in SQL Server can drop by `90-99%+`.
- SQL Server logs only metadata rows and summary updates, not every presence pair.
- if bitmaps are stored as `VARBINARY(MAX)` inside SQL Server, storage still improves, but blob writes remain logged; filesystem artifacts avoid the database log bottleneck more cleanly.

UI impact:

- frequency filtering becomes faster via summary rows;
- project presence is served from project artifacts or sample-artifact-derived project grouping;
- allele detail requires decompressing one bitmap and resolving sample ordinals;
- sample search/filter uses the secondary sample-oriented artifact;

This is the best long-term fit for the VM/VPN/log-cap constraint.

### Parquet/DuckDB Artifacts

Storage reduction:

- commonly `5x-20x` compared with rowstore for integer presence facts, depending on sorting, partitioning, and compression.

Logging reduction:

- similar to filesystem bitmap artifacts if SQL Server stores only metadata and summaries: potentially `90-99%+` less SQL transaction log volume for raw presence data.

UI impact:

- good for analytical queries and ad hoc exploration;
- may be slower than per-allele bitmaps for single-allele detail unless partitioned carefully;
- adds a local query engine dependency.

This is a good second choice if analytics flexibility matters more than simplest UI-serving performance.

## Comparison Matrix

| Option | SQL log reduction | Storage reduction | UI compatibility | Operational fit behind VPN | Recommendation |
| --- | ---: | ---: | --- | --- | --- |
| Current rowstore | none | none | native | poor with 2 GB log cap | do not scale |
| Batched rowstore | high peak-log reduction, little total-log reduction | none | native | good short term | implement now |
| Rowstore + fewer indexes | moderate | small | native | good short term | implement with batching |
| SQL columnstore | moderate, workload-dependent | `4x-10x` typical | medium | okay, still log-capped | consider prototype |
| Filesystem compressed bitmaps + SQL summaries | `90-99%+` for raw presence | `10x-100x+` depending density | high with query helper changes | best | recommended |
| Parquet/DuckDB + SQL summaries | `90-99%+` for raw presence | `5x-20x` typical | medium-high | good if dependency allowed | good alternative |

## Recommended Phased Plan

Phase 1: Confirm and stabilize production logging.

- Run the diagnostics above.
- If `FULL` recovery is required, configure frequent transaction log backups.
- Increase log file size to handle the largest expected batch.
- Stop relying on weekly resets as the only truncation event.

Phase 2: Keep imports artifact-backed and resumable.

- Write compressed artifacts for both lookup orientations.
- Store artifact manifests and summary rows in SQL Server.
- Add richer import batch metadata if restart/resume support becomes necessary.
- Refresh frequency/sample counts only for touched alleles.

Implementation status:

- Presence import scripts now use one artifact-backed path. There is no user-facing storage choice.
- Sample imports write both allele-to-sample and sample-to-allele compressed artifacts, plus SQL summary rows.
- Project imports write both allele-to-project and project-to-allele compressed artifacts, plus SQL summary rows.
- Compressed artifacts default to `/srv/hapsearch/production/presence_artifacts` in production and `/srv/hapsearch/development/presence_artifacts` in development, or `PRESENCE_ARTIFACT_DIR`.
- Sample imports update `microhaplotypes.sample_count` and `microhaplotypes.frequency` from summary rows so existing frequency filters keep working.
- The Haplotype Explorer's sample filter can resolve matching haplotypes through sample-oriented artifacts.
- Allele detail sample/project panels can resolve through compressed artifacts.

Phase 3: Measure and tune.

- Measure compression, import time, query time, and log growth on a representative multi-file dataset.
- Add caches or shard artifacts by chromosome/species if query latency warrants it.
- Consider Parquet/DuckDB only if future analytics outgrow bitmap-oriented UI serving.

Phase 4: Initialize cleanly.

- Reinitialize dev/prod schemas from `schema_mssql.sql`.
- Keep old experimental databases disposable until the artifact path is validated.

## Recommendation

Do not solve this by loading presence edges into SQL Server and tuning batch sizes. With a 2 GB log cap and limited admin control, the durable solution is to avoid the row-per-presence write altogether.

The recommended design is now implemented as the main path:

- SQL Server stores metadata, artifact manifests, and compact summaries.
- The raw presence matrix lives in bidirectional compressed bitmap artifacts.
- The UI reads summaries for counts/frequencies and artifacts for sample/project detail and sample filtering.
