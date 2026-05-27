# HaploSearch

HaploSearch is a web-based microhaplotype analysis platform for searching, visualizing, and sharing haplotype data across breeding projects and species.

The app provides:

- Overview dashboards for species, marker, haplotype, sample, project, and PI coverage.
- Marker exploration with multiple sequence alignment and variant annotation views.
- Haplotype exploration with sample, project, and collaborator context.
- Import utilities for FASTA, sample metadata, project presence, sample presence, and variant annotations.
- Docker-based deployment for local development and production-style environments.

## Requirements

- Docker Desktop for the containerized workflow.
- Python 3.13+ for local development outside Docker.
- Microsoft SQL Server and ODBC Driver 18 for SQL Server for the default database configuration.
- Optional alignment tools such as MUSCLE or Clustal Omega when running outside Docker.

## Quick Start With Docker

### Local Development With Bundled SQL Server

Use this path when you want Docker Compose to start both HaploSearch and a local SQL Server container. This stack sets `APP_ENV=local-dev` and bypasses ORCID sign-in for local-only work.

1. Create a local environment file:

   ```bash
   cp .env.example .env.development.local
   ```

   Update the copied file with local SQL Server credentials. For the bundled SQL Server container, include `ACCEPT_EULA=Y` and set both `SA_PASSWORD` and `MSSQL_PASSWORD` to the same strong password.

2. Start the local development stack:

   ```bash
   docker compose -f docker-compose.dev-local.yml up -d --build
   ```

3. Open the app:

   ```text
   http://localhost:5000
   ```

4. Stop the stack:

   ```bash
   docker compose -f docker-compose.dev-local.yml down
   ```

### Development Against an Existing SQL Server

Use this path when SQL Server already exists outside the Compose stack. This stack requires ORCID authentication.

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

The app is available at:

```text
http://localhost:5000
```

### Production-Style Compose

The default `docker-compose.yml` maps host port `5080` to container port `5000` and expects production environment variables in `.env.production`.

```bash
docker compose up -d --build
```

The app is available at:

```text
https://localhost:5080
```

TLS is enabled in the production compose file and expects certificate/key mounts at the paths shown in `docker-compose.yml`. Production requires ORCID authentication.

## Local Python Development

1. Create and activate a virtual environment:

   ```bash
   python3.13 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables in `.env`.

4. Initialize the database:

   ```bash
   python scripts/init_database.py --force
   ```

5. Start the app:

   ```bash
   python app.py
   ```

The app defaults to `http://localhost:5000` in development.

## Environment Variables

Common settings:

```bash
APP_ENV=development
APP_PORT=5000
DEBUG_MODE=true
SECRET_KEY=change-me
MSSQL_SERVER=localhost
MSSQL_PORT=1433
MSSQL_DATABASE=HaploSearch
MSSQL_USER=sa
MSSQL_PASSWORD=your-password
MSSQL_DRIVER="ODBC Driver 18 for SQL Server"
MSSQL_TRUST_SERVER_CERTIFICATE=true
```

Optional ORCID OAuth settings:

```bash
ORCID_CLIENT_ID=your-client-id
ORCID_CLIENT_SECRET=your-client-secret
```

Authentication bypass settings:

```bash
BYPASS_ORCID_AUTH=false
BYPASS_AUTH_WHITELIST=false
BYPASS_DEV_ORCID=0000-0000-0000-0000
BYPASS_DEV_NAME="Developer"
BYPASS_DEV_ROLE=admin
```

`BYPASS_ORCID_AUTH=true` only works when `APP_ENV=local-dev`, which is set by `docker-compose.dev-local.yml`. The regular development and production Compose files explicitly keep ORCID authentication required.

## Data Import

Initialize or reset the database schema:

```bash
python scripts/init_database.py --force
```

Import data with the scripts in `scripts/`:

- `import_fasta.py`: import FASTA sequence files and extract haplotypes.
- `import_samples.py`: import sample metadata and project associations.
- `import_project_presence.py`: import project-level presence/absence data.
- `import_sample_presence.py`: import sample-level presence/absence data.
- `import_variants.py`: import variant annotations.
- `import_botloci.py`: import `.botloci` bottom-strand locus lookup files.
- `detect_variants.py`: detect variants from sequence data.

See each script's help output for supported arguments:

```bash
python scripts/import_fasta.py --help
```

## Testing

Run the test suite with:

```bash
pytest
```

If `pytest` is not installed, install the development dependency first:

```bash
pip install pytest
```

## Project Structure

```text
alignment/   Sequence alignment and variant annotation helpers
assets/      Dash CSS assets
auth/        ORCID and session authentication helpers
data/        Local/imported data files
database/    Database manager, queries, and bulk import helpers
design/      Color tokens and visualization palette documentation
pages/       Dash page modules
scripts/     Database initialization and import utilities
static/      Images and static assets
templates/   Flask templates
tests/       Automated tests
```

## Troubleshooting

### Port Already In Use

Change the host-side port mapping in the relevant Compose file. For example, change `5000:5000` to `5001:5000`, then open `http://localhost:5001`.

### Docker Is Not Running

Launch Docker Desktop and wait for it to finish starting before running Docker Compose commands.

### SQL Server Connection Fails

- Confirm SQL Server is running and reachable from the app container.
- Confirm `MSSQL_SERVER`, `MSSQL_PORT`, `MSSQL_DATABASE`, `MSSQL_USER`, and `MSSQL_PASSWORD`.
- Use `MSSQL_TRUST_SERVER_CERTIFICATE=true` for local/internal SQL Server instances with self-signed certificates.
- Confirm the configured ODBC driver name matches the installed driver.

### Rebuild Containers

```bash
docker compose -f docker-compose.dev-local.yml down
docker compose -f docker-compose.dev-local.yml up -d --build
```

## Additional Documentation

- [Microsoft SQL Server setup guide](MSSQL_SETUP.md)
- [Product plan](HaploSearch_Plan_Document.md)
- [Color palette design](design/color_palettes.md)
