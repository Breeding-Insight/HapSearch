# Cloud Run deployment

HapSearch runs on Cloud Run as a scale-to-zero service. All research data lives in
one SQLite file that ships inside the container image, so the service needs no
database server, no Cloud SQL connection and no VPC connector. The ORCID allowlist
lives in Firestore, like HapApp and AlloMate, so people can be added or removed
without rebuilding the image. Nothing is billed while the service is idle except the
stored image and Firestore storage.

## How the data gets into the image

The database is rebuilt from scratch from the files in
`Breeding-Insight/alfalfa_haplotype_db` and baked into the image. Cloud Build
does this on every run (`cloudbuild.yaml`): clone the data repository at a tag,
run `scripts/build_database.py`, build the image, deploy. Cloud Run switches
revisions atomically, so visitors never see a half-updated database. See
[updating-data.md](updating-data.md) for adding data and publishing.

Inside the container the file is opened read-only and immutable
(`SQLITE_READ_ONLY=true`, set in the `Dockerfile`). Each Gunicorn worker keeps the
presence bitmaps it has read in memory; they cannot go stale because a new database
always means a new revision.

### Migrating from SQL Server

Research data does not need migrating: it is rebuilt from the data repository.
The migration is useful for the user allowlist, which can then be copied into
Firestore with `manage_users.py --store firestore copy-from-sqlite` (below). It
copies every table with its IDs, and converts the legacy `.npz` lookup artifacts
into bitmap rows inside the database. It needs `pyodbc` and an ODBC
driver, which are no longer app dependencies:

```bash
pip install pyodbc
python scripts/migrate_mssql_to_sqlite.py --mssql-connection-string "DRIVER={ODBC Driver 18 for SQL Server};SERVER=...;DATABASE=HaploSearch;UID=...;PWD=...;TrustServerCertificate=yes" --artifact-dir /srv/hapsearch/production/presence_artifacts --output data/hapsearch.db
```

## Firestore (user allowlist)

Create a Firestore Standard database in Native mode, in the same project:

```text
database ID: hapsearch-db
location: us-west1
security rules: deny all reads and writes from browsers and mobile clients
```

HapSearch only reads it, from the Python server through Google IAM. Each allowed
person is a `users/{orcid_id}` document:

```json
{
  "orcid_id": "0000-0000-0000-0000",
  "display_name": "Example User",
  "email": "user@example.org",
  "role": "admin",
  "is_active": true
}
```

`created_at` is set when someone is added; `role` is kept for consistency with the
other BI apps but HapSearch does not use it. Set `is_active` to `false` to remove
access; it takes effect at the person's next sign-in.

There is no user-management page in the app. Edit the documents in the Firestore
console, or use the CLI with your own Application Default Credentials
(`gcloud auth application-default login`):

```bash
export GOOGLE_CLOUD_PROJECT=PROJECT_ID FIRESTORE_DATABASE=hapsearch-db
python scripts/manage_users.py --store firestore add --orcid 0000-0000-0000-0000 --name "Example User"
python scripts/manage_users.py --store firestore list
python scripts/manage_users.py --store firestore deactivate --orcid 0000-0000-0000-0000
python scripts/manage_users.py --store firestore copy-from-sqlite
```

Sign-ins are not stored. Each successful sign-in writes one log line,
`Sign-in: orcid_id=...`, which you can search in Cloud Logging.

`copy-from-sqlite` reads the `users` table from `SQLITE_DB_PATH` (for example the
output of the SQL Server migration) and skips anyone already in Firestore.

The store is chosen by `HAPSEARCH_USER_STORE`. It defaults to `firestore` on Cloud Run
(detected from `K_SERVICE`) and to `sqlite` everywhere else, so local development and
the VM keep using the `users` table. With Firestore, startup performs one read and
stops with a clear message if the database name or IAM role is wrong.

## Service identity

Create a service account such as `hapsearch-cloud-run` and grant it:

- `roles/datastore.viewer` on the project (read-only Firestore access)
- `roles/secretmanager.secretAccessor` on each HapSearch secret

Attach it as the Cloud Run service identity. Do not create a JSON key.

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
  --service-account=hapsearch-cloud-run@PROJECT_ID.iam.gserviceaccount.com \
  --port=8080 \
  --cpu=1 \
  --memory=1Gi \
  --cpu-throttling \
  --cpu-boost \
  --min-instances=0 \
  --max-instances=3 \
  --execution-environment=gen2 \
  --set-env-vars="APP_ENV=production,DEBUG_MODE=false,TLS_ENABLED=false,FIRESTORE_DATABASE=hapsearch-db,GOOGLE_CLOUD_PROJECT=PROJECT_ID,HAPSEARCH_LANDING_URL=https://breeding-insight.github.io/HapSearch/" \
  --set-secrets="SECRET_KEY=hapsearch-secret-key:latest,ORCID_CLIENT_ID=hapsearch-orcid-client-id:latest,ORCID_CLIENT_SECRET=hapsearch-orcid-client-secret:latest"
```

Deploy through the Cloud Build trigger (`cloudbuild.yaml`), which builds the
database first. `gcloud run deploy --source .` also works after building
`data/hapsearch.db` locally; `.gcloudignore` keeps that file and leaves out the
raw import files.

Cloud Run terminates HTTPS, so keep `TLS_ENABLED=false`. The ORCID redirect URI must be
`https://YOUR-SERVICE-URL/auth/callback`.

## Landing page

Signed-out visitors to `/` are redirected to `HAPSEARCH_LANDING_URL` (when it is empty,
the built-in landing page is served as before). The BI pattern puts that page on GitHub
Pages with the shared `wake.js` script; see the HapApp and AlloMate `landing/` folders.

## Known limits

- **Imports do not run on Cloud Run.** Build the database locally or in Cloud Build.
