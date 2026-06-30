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

# Microsoft SQL Server configuration
DATABASE_SERVER = os.getenv('MSSQL_SERVER', 'localhost')
DATABASE_NAME = os.getenv('MSSQL_DATABASE', 'HaploSearch')
DATABASE_USER = os.getenv('MSSQL_USER', 'sa')
DATABASE_PASSWORD = os.getenv('MSSQL_PASSWORD', '')
DATABASE_DRIVER = os.getenv('MSSQL_DRIVER', 'ODBC Driver 18 for SQL Server')
DATABASE_PORT = os.getenv('MSSQL_PORT', '1433')

# Build connection string if not provided directly
# ODBC 18: use TrustServerCertificate=yes for internal/VPN servers with self-signed certs
_conn_opts = f'DRIVER={{{DATABASE_DRIVER}}};SERVER={DATABASE_SERVER},{DATABASE_PORT};DATABASE={DATABASE_NAME};UID={DATABASE_USER};PWD={DATABASE_PASSWORD}'
if os.getenv('MSSQL_TRUST_SERVER_CERTIFICATE', '').lower() in ('true', '1', 'yes'):
    _conn_opts += ';TrustServerCertificate=yes'
DATABASE_CONNECTION_STRING = os.getenv('MSSQL_CONNECTION_STRING', _conn_opts)

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
if APP_ENV == 'production':
    DEFAULT_PRESENCE_ARTIFACT_DIR = '/srv/hapsearch/production/presence_artifacts'
elif APP_ENV == 'local-dev':
    DEFAULT_PRESENCE_ARTIFACT_DIR = os.path.join(DATA_DIR, 'presence_artifacts')
else:
    DEFAULT_PRESENCE_ARTIFACT_DIR = '/srv/hapsearch/development/presence_artifacts'
PRESENCE_ARTIFACT_DIR = os.getenv(
    'PRESENCE_ARTIFACT_DIR',
    DEFAULT_PRESENCE_ARTIFACT_DIR
)

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
