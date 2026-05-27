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

# Install MUSCLE
RUN wget --timeout=30 --tries=3 https://github.com/rcedgar/muscle/releases/download/v5.2/muscle-linux-aarch64-v5.2 -O /usr/local/bin/muscle \
    && chmod +x /usr/local/bin/muscle \
    || (wget --timeout=30 --tries=3 https://github.com/rcedgar/muscle/releases/download/v5.2/muscle-linux-x64-v5.2 -O /usr/local/bin/muscle \
    && chmod +x /usr/local/bin/muscle)

# Upgrade pip first for better wheel support
RUN pip install --upgrade pip setuptools wheel

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared resources
COPY database/ ./database/
COPY design/ ./design/
COPY scripts/ ./scripts/
COPY schema_mssql.sql ./

# Copy application files
COPY app.py .
COPY config.py .
COPY dash_app.py .
COPY assets/ ./assets/
COPY static/ ./static/
COPY pages/ ./pages/
COPY alignment/ ./alignment/
COPY auth/ ./auth/
COPY templates/ ./templates/
COPY data/ ./data/

# Create a dedicated non-root user for runtime
RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app && \
    chown -R app:app /app

# Expose single internal app port; external ports are mapped via docker-compose
EXPOSE 5000

# Run the app
USER app
CMD ["python", "app.py"]

# Dev-only stage: add Microsoft ODBC Driver for SQL Server (local dev container)
FROM base AS dev
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
USER app
