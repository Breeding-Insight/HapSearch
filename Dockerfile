FROM python:3.13-slim AS base

WORKDIR /app

# Install system dependencies, build tools, and alignment tools
# Use DEBIAN_FRONTEND=noninteractive and add timeout settings
RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y --no-install-recommends \
    wget \
    build-essential \
    g++ \
    ca-certificates \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Try to install clustalo separately (may not be available in newer Debian)
# If it fails, continue anyway - you can install it manually if needed
RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    (apt-get install -y --no-install-recommends clustalo || echo "clustalo not available, skipping") && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* || true

# Install MUSCLE for the image's CPU architecture (Cloud Run runs linux/amd64).
RUN case "$(dpkg --print-architecture)" in \
        arm64) muscle_asset=muscle-linux-aarch64-v5.2 ;; \
        *) muscle_asset=muscle-linux-x86.v5.2 ;; \
    esac && \
    wget --timeout=30 --tries=3 \
        "https://github.com/rcedgar/muscle/releases/download/v5.2/${muscle_asset}" \
        -O /usr/local/bin/muscle && \
    chmod +x /usr/local/bin/muscle

# Upgrade pip first for better wheel support
RUN pip install --upgrade pip setuptools wheel

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The SQLite database changes only when data is re-imported, so it gets its
# own layer before the code: code-only rebuilds reuse the cached data layer.
# Build it first (see docs/cloud-run.md); the build fails if it is missing.
COPY data/hapsearch.db ./data/hapsearch.db

# Copy shared resources
COPY database/ ./database/
COPY design/ ./design/
COPY scripts/ ./scripts/
COPY schema_sqlite.sql ./

# Copy application files
COPY app.py .
COPY config.py .
COPY dash_app.py .
COPY gunicorn.conf.py .
COPY assets/ ./assets/
COPY static/ ./static/
COPY pages/ ./pages/
COPY alignment/ ./alignment/
COPY auth/ ./auth/
COPY templates/ ./templates/

# Create a dedicated non-root user for runtime
RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app && \
    chown -R app:app /app

# The image's database is opened read-only (immutable). Local compose files
# mount a writable copy and set SQLITE_READ_ONLY=false.
ENV SQLITE_DB_PATH=/app/data/hapsearch.db \
    SQLITE_READ_ONLY=true \
    APP_PORT=8080

# Cloud Run injects PORT (8080 by default), which gunicorn.conf.py prefers
# over APP_PORT; the compose files set APP_PORT=5000.
EXPOSE 8080

# Run the app with a production-grade WSGI server. Gunicorn keeps a master
# process alive to replace failed workers and does not run Flask's debug
# reloader, so application workers cannot silently reload inside the container.
USER app
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:server"]

# Dev target used by the docker-compose files, which mount the source tree.
FROM base AS dev
