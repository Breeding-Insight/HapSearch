"""Configuration settings for Haplosearch application"""

import os

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Environment: 'local-dev', 'development', or 'production'
APP_ENV = os.getenv('APP_ENV', 'development')

# SQLite configuration
# The database is a single read-mostly file that ships inside the container
# image on Cloud Run. Set SQLITE_READ_ONLY=true there so connections open the
# file immutably (no locks, no journal) since the image filesystem is never
# written back.
SQLITE_DB_PATH = os.getenv(
    'SQLITE_DB_PATH',
    os.path.join(os.path.dirname(__file__), 'data', 'hapsearch.db'),
)
SQLITE_READ_ONLY = os.getenv('SQLITE_READ_ONLY', 'false').lower() in ('true', '1', 'yes')

# Application configuration
APP_TITLE = "HapSearch - Microhaplotype Browser"
APP_HOST = "0.0.0.0"
# Port defaults: 5000 for development, 5080 for production
APP_PORT = int(os.getenv('APP_PORT', '5000' if APP_ENV == 'development' else '5080'))
DEBUG_MODE = os.getenv('DEBUG_MODE', 'true').lower() in ('true', '1', 'yes')
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-change-in-production')
TLS_ENABLED = os.getenv('TLS_ENABLED', 'false').lower() in ('true', '1', 'yes')
TLS_CERT_PATH = os.getenv('TLS_CERT_PATH', '/cert.pem')
TLS_KEY_PATH = os.getenv('TLS_KEY_PATH', '/key.pem')
SSL_CONTEXT = (TLS_CERT_PATH, TLS_KEY_PATH) if TLS_ENABLED else None

# Public landing page (GitHub Pages) for the Cloud Run deployment. Signed-out
# visitors to / and sign-outs are redirected there; when it is empty, / goes
# straight to ORCID sign-in.
LANDING_URL = os.getenv('HAPSEARCH_LANDING_URL', '').strip()

# ORCID allowlist backend: 'firestore' on Cloud Run (K_SERVICE is set there),
# 'sqlite' (the users table) elsewhere. The SQLite file is read-only on Cloud
# Run, so the Admin tab needs Firestore there.
USER_STORE = os.getenv(
    'HAPSEARCH_USER_STORE',
    'firestore' if os.getenv('K_SERVICE') else 'sqlite',
).strip().lower()
GOOGLE_CLOUD_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT', os.getenv('GCLOUD_PROJECT', '')).strip()
FIRESTORE_DATABASE = os.getenv('FIRESTORE_DATABASE', '(default)').strip()
# Check the user store with one read at startup so a wrong database name or
# missing IAM role fails the deployment instead of the first sign-in.
USER_STORE_PREFLIGHT = os.getenv(
    'HAPSEARCH_USER_STORE_PREFLIGHT',
    'true' if USER_STORE == 'firestore' else 'false',
).lower() in ('true', '1', 'yes')

# Local dev only: skip ORCID OAuth and create a development admin session.
BYPASS_ORCID_AUTH = (
    APP_ENV == 'local-dev'
    and os.getenv('BYPASS_ORCID_AUTH', 'false').lower() in ('true', '1', 'yes')
)

# Dev only: after ORCID OAuth, skip whitelist lookup for a specific ORCID.
BYPASS_AUTH_WHITELIST = os.getenv('BYPASS_AUTH_WHITELIST', 'false').lower() in ('true', '1', 'yes')
BYPASS_DEV_ORCID = os.getenv('BYPASS_DEV_ORCID', '0009-0002-4298-0820')
BYPASS_DEV_NAME = os.getenv('BYPASS_DEV_NAME', 'Tyler Slonecki')
BYPASS_DEV_ROLE = os.getenv('BYPASS_DEV_ROLE', 'admin')

# ORCID OAuth2 configuration
ORCID_CLIENT_ID = os.getenv('ORCID_CLIENT_ID', '')
ORCID_CLIENT_SECRET = os.getenv('ORCID_CLIENT_SECRET', '')

if APP_ENV == 'production':
    ORCID_BASE_URL = 'https://orcid.org'
    ORCID_API_URL = 'https://pub.orcid.org/v3.0'
else:
    ORCID_BASE_URL = 'https://sandbox.orcid.org'
    ORCID_API_URL = 'https://pub.sandbox.orcid.org/v3.0'

ORCID_AUTHORIZE_URL = f'{ORCID_BASE_URL}/oauth/authorize'
ORCID_TOKEN_URL = f'{ORCID_BASE_URL}/oauth/token'

# Data directories
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
FASTA_DIR = os.path.join(DATA_DIR, 'fasta')
MARKERS_DIR = os.path.join(DATA_DIR, 'markers')
SAMPLES_DIR = os.path.join(DATA_DIR, 'samples')
PROJECTS_DIR = os.path.join(DATA_DIR, 'projects')
# Maximum presence matrices each worker keeps decoded in memory. Each one is a
# packed bitmap (roughly entities x microhaplotypes / 8 bytes).
PRESENCE_CACHE_MAX_ARTIFACTS = int(os.getenv('PRESENCE_CACHE_MAX_ARTIFACTS', '256'))

# Dropbox configuration (for metadata sync)
DROPBOX_ACCESS_TOKEN = os.getenv('DROPBOX_ACCESS_TOKEN', '')

# MSA Visualization settings (matches design/colors.py NUCLEOTIDE_COLORS)
# Using Shiny app core palette
MSA_BASE_COLORS = {
    'A': '#319B42',  # Adenine - Green Core
    'G': '#EFB526',  # Guanine - Yellow Core
    'C': '#48A9C5',  # Cytosine - Azure Core
    'T': '#E43F4F',  # Thymine - Red Core
    '-': '#FFFFFF',  # Gap - White
    'N': '#C8CACA'   # Unknown - Grey Lite
}

MSA_VARIANT_COLORS = {
    'SNP': '#FF6600',        # Orange
    'Indel': '#CC0000',      # Red
    'Target_SNP': '#9900CC'  # Purple
}

# Export settings
EXPORT_MAX_SEQUENCES = 10000
