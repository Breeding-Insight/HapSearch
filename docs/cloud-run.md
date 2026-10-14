# Cloud Run deployment

HapSearch runs on Cloud Run as a scale-to-zero service. All research data lives in
one SQLite file that ships inside the container image, so the service needs no
database server, no Cloud SQL connection and no VPC connector. The ORCID allowlist
lives in Firestore, like HapApp and AlloMate, so people can be added or removed
without rebuilding the image. Nothing is billed while the service is idle except the
stored image and Firestore storage.

## First-time setup

1. **Run the setup script in Cloud Shell** (console.cloud.google.com, the `>_`
   button; it already has `gcloud` and your login), in the same project as HapApp
   and AlloMate:

   ```bash
   git clone --branch feature-MSA https://github.com/Breeding-Insight/HapSearch.git
   cd HapSearch && bash scripts/setup_cloud_run.sh
   ```

   It is safe to re-run. It creates the Artifact Registry repository (keeping the
   last 5 images), the `hapsearch-db` Firestore database, the app and Cloud Build
   service accounts with only the roles below, and the secrets. It copies the
   shared ORCID credentials from AlloMate's or HapApp's secrets when present, and
   can add the first allowlisted user.
2. **Connect GitHub to Cloud Build** (Repositories → 2nd gen, region `us-west1`,
   connection name `github`). This installs the "Google Cloud Build" GitHub App on
   Breeding-Insight; an org owner may need to approve it. Link both
   `Breeding-Insight/HapSearch` and `Breeding-Insight/alfalfa_haplotype_db`. Builds
   read the data repository through this connection with short-lived read-only
   tokens, so no personal GitHub token is stored and nothing expires.
3. **Create the trigger** (the script prints the exact settings): manual invocation,
   repository `Breeding-Insight-HapSearch`, branch `feature-MSA`, `cloudbuild.yaml`,
   service account `hapsearch-cloud-build`. Each data repository's link name must
   match its `link` in `data_sources.toml` (`Breeding-Insight-alfalfa_haplotype_db`).
4. **Run the trigger.** The first run creates the service, fully configured.
5. **Add the ORCID redirect URI** `https://hapsearch-PROJECT_NUMBER.us-west1.run.app/auth/callback`
   to the shared BI ORCID application, then open `/health` and sign in.

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

## Service identities

`scripts/setup_cloud_run.sh` creates `hapsearch-cloud-run`, the app's identity, with:

- `roles/datastore.viewer` on the project (read-only Firestore access)
- `roles/secretmanager.secretAccessor` on the session key and ORCID secrets

and `hapsearch-cloud-build`, the trigger's identity, with `roles/run.admin`,
`roles/artifactregistry.writer`, `roles/logging.logWriter`,
`roles/cloudbuild.readTokenAccessor` (read-only tokens for linked repositories), and
permission to deploy as `hapsearch-cloud-run`. No JSON keys or GitHub tokens are
created.

## Service settings

- container port: `8080` (the image honors the injected `PORT`)
- minimum instances: `0`, with startup CPU boost
- request-based billing (`--cpu-throttling`)
- CPU `1`, memory `1 GiB`: each of the two Gunicorn workers peaks around 220 MB
  with every presence bitmap cached (measured on a Mac with the current data)
- public ingress; access to `/app/` is controlled by ORCID sign-in
- `GET /health` answers `200` without touching the database, for the landing page's
  wake-up script; `/robots.txt` disallows all crawling

These settings, the environment variables and the secret references all live in
the deploy step of `cloudbuild.yaml`, so every run applies them. Set
`_LANDING_URL` on the trigger once the GitHub Pages landing page exists.

Cloud Run terminates HTTPS, so keep `TLS_ENABLED=false`. The ORCID redirect URI must be
`https://YOUR-SERVICE-URL/auth/callback`.

## Landing page

The public landing page is the static site in `landing/`, published to GitHub Pages by
`.github/workflows/pages.yml` on every push to `feature-MSA` that changes it. It follows the
Breeding Insight pattern shared with HapApp and AlloMate: its sign-in links point at the
Cloud Run service, and `landing/assets/wake.js` wakes the service through `/health` when a
visitor clicks one, showing a "Starting HapSearch…" state during a cold start. Keep
`wake.js` identical to the copies in the other BI app repositories.

The service URL appears three times in `landing/index.html` (both sign-in links and the
`wake.js` script tag); update all three together if it changes.

To set it up once:

1. In the GitHub repository, set **Settings → Pages → Source** to **GitHub Actions**.
2. Push to `main` (or run the workflow manually) and note the published URL, e.g.
   `https://breeding-insight.github.io/HapSearch/`.
3. Set `_LANDING_URL` on the Cloud Build trigger to that URL and redeploy.

Signed-out visitors to `/` are then redirected to `HAPSEARCH_LANDING_URL`. While it is
empty, the built-in page in `templates/landing.html` is served instead.

## Known limits

- **Imports do not run on Cloud Run.** Build the database locally or in Cloud Build.
