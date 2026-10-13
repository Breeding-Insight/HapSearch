# Cloud Run deployment

HapSearch runs on Cloud Run as a scale-to-zero service. All data lives in one SQLite
file that ships inside the container image, so the service needs no database server,
no Cloud SQL connection and no VPC connector. Nothing is billed while the service is
idle except the stored image.

## How the data gets into the image

The data changes only when new FASTA or presence/absence files are imported, so the
database is built ahead of time, then baked into the image:

1. Build `data/hapsearch.db` with the import scripts (below), or once from the old
   SQL Server with `scripts/migrate_mssql_to_sqlite.py`.
2. Run `python scripts/init_database.py --optimize` on it. This refreshes the query
   planner's statistics and compacts the file. Skipping it makes artifact-backed
   filters (such as the sample filter) roughly 100 times slower.
3. Upload it to Cloud Storage and build a new image. Cloud Run switches revisions
   atomically, so visitors never see a half-updated database.

Inside the container the file is opened read-only and immutable
(`SQLITE_READ_ONLY=true`, set in the `Dockerfile`). Each Gunicorn worker keeps the
presence bitmaps it has read in memory; they cannot go stale because a new database
always means a new revision.

### Building the database

```bash
python scripts/init_database.py --force
python scripts/import_fasta.py data/fasta/alfalfa_allele_db_v052.fa "Medicago sativa" --common-name Alfalfa
python scripts/import_botloci.py data/markers/20201030-BI-Alfalfa_SNPs_DArTag-probe-design_f180bp.botloci
python scripts/import_sample_presence.py data/presence_absence/sample --species-id 1
python scripts/import_project_presence.py data/presence_absence/project/20260413-alfalfa-v52-madc-filter-miss-files_hapPA_matrix.csv
python scripts/manage_users.py add --orcid 0000-0000-0000-0000 --name "Example User" --role admin
python scripts/init_database.py --optimize
```

With the current alfalfa data this takes about 3 minutes and produces a 74 MB file.

### Migrating from SQL Server instead

The migration copies every table with its IDs, and converts the legacy `.npz`
lookup artifacts into bitmap rows inside the database. It needs `pyodbc` and an ODBC
driver, which are no longer app dependencies:

```bash
pip install pyodbc
python scripts/migrate_mssql_to_sqlite.py --mssql-connection-string "DRIVER={ODBC Driver 18 for SQL Server};SERVER=...;DATABASE=HaploSearch;UID=...;PWD=...;TrustServerCertificate=yes" --artifact-dir /srv/hapsearch/production/presence_artifacts --output data/hapsearch.db
```

## Service settings

- container port: `8080` (the image honors the injected `PORT`)
- minimum instances: `0`, with startup CPU boost
- request-based billing (`--cpu-throttling`)
- CPU `1`, memory `1 GiB`: each of the two Gunicorn workers peaks around 220 MB
  with every presence bitmap cached (measured on a Mac with the current data)
- public ingress; access to `/app/` is controlled by ORCID sign-in
- `GET /health` answers `200` without touching the database, for the landing page's
  wake-up script; `/robots.txt` disallows all crawling

Example deployment, after replacing the uppercase values:

```bash
gcloud run deploy hapsearch \
  --source . \
  --region=us-west1 \
  --allow-unauthenticated \
  --port=8080 \
  --cpu=1 \
  --memory=1Gi \
  --cpu-throttling \
  --cpu-boost \
  --min-instances=0 \
  --max-instances=3 \
  --execution-environment=gen2 \
  --set-env-vars="APP_ENV=production,DEBUG_MODE=false,TLS_ENABLED=false,HAPSEARCH_LANDING_URL=https://breeding-insight.github.io/HapSearch/" \
  --set-secrets="SECRET_KEY=hapsearch-secret-key:latest,ORCID_CLIENT_ID=hapsearch-orcid-client-id:latest,ORCID_CLIENT_SECRET=hapsearch-orcid-client-secret:latest"
```

`--source .` uploads the working tree using `.gcloudignore`, which keeps
`data/hapsearch.db` and leaves out the raw import files. For a Cloud Build trigger,
use `cloudbuild.yaml` and set `_DATABASE_URI` to the database's Cloud Storage path.

Cloud Run terminates HTTPS, so keep `TLS_ENABLED=false`. The ORCID redirect URI must be
`https://YOUR-SERVICE-URL/auth/callback`.

## Landing page

Signed-out visitors to `/` are redirected to `HAPSEARCH_LANDING_URL` (when it is empty,
the built-in landing page is served as before). The BI pattern puts that page on GitHub
Pages with the shared `wake.js` script; see the HapApp and AlloMate `landing/` folders.

## Known limits

- **User administration is read-only on Cloud Run.** The ORCID allowlist (`users`
  table) ships inside the image, so the Admin tab cannot add or change users there and
  `last_login` is not recorded. Manage users with `scripts/manage_users.py` before
  building, or move users to Firestore (`users/{orcid_id}`) like HapApp and AlloMate.
- **Imports do not run on Cloud Run.** Build the database locally or in Cloud Build.
