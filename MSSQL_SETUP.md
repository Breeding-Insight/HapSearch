# Microsoft SQL Server Setup Guide

This guide explains how to configure HaploSearch to use Microsoft SQL Server.

## Overview

The application uses Microsoft SQL Server as its database backend. Connection details are controlled through environment variables loaded by `config.py`.

## Prerequisites

1. **Microsoft SQL Server** installed and running, or the `mssql` service from `docker-compose.dev-local.yml`.
2. **ODBC Driver 18 for SQL Server** installed on the machine or container running the application.
   - Download from: <https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server>
   - Driver 17 can also work, but this project defaults to Driver 18.
3. **Python package**: `pyodbc`, included in `requirements.txt`.

## Configuration

### Option 1: Environment Variables

Set the following environment variables:

```bash
export MSSQL_SERVER=your-server-name
export MSSQL_DATABASE=HaploSearch
export MSSQL_USER=your-username
export MSSQL_PASSWORD=your-password
export MSSQL_PORT=1433
export MSSQL_DRIVER="ODBC Driver 18 for SQL Server"
export MSSQL_TRUST_SERVER_CERTIFICATE=true
```

Or use a full connection string:

```bash
export MSSQL_CONNECTION_STRING="DRIVER={ODBC Driver 18 for SQL Server};SERVER=your-server,1433;DATABASE=HaploSearch;UID=your-username;PWD=your-password;TrustServerCertificate=yes"
```

### Option 2: Local `.env` Files

`config.py` loads `.env` automatically when `python-dotenv` is available. The Docker Compose files use these environment files:

- `.env.development.local` for `docker-compose.dev-local.yml`
- `.env.development` for `docker-compose.dev.yml`
- `.env.production` for `docker-compose.yml`

Keep these files local because they may contain credentials.

### Option 3: Modify `config.py`

Direct edits to `config.py` are possible, but environment variables are preferred. If needed, set:

```python
DATABASE_SERVER = 'your-server-name'
DATABASE_NAME = 'HaploSearch'
DATABASE_USER = 'your-username'
DATABASE_PASSWORD = 'your-password'
DATABASE_DRIVER = 'ODBC Driver 18 for SQL Server'
DATABASE_PORT = '1433'
```

## Database Initialization

### Step 1: Create the Database

Connect to your Microsoft SQL Server instance and create the database:

```sql
CREATE DATABASE HaploSearch;
```

### Step 2: Initialize Schema

Run the initialization script:

```bash
# Set environment variables first (see above)
python scripts/init_database.py --force
```

Or specify connection string directly:

```bash
python scripts/init_database.py \
  --connection-string "DRIVER={ODBC Driver 18 for SQL Server};SERVER=your-server,1433;DATABASE=HaploSearch;UID=your-username;PWD=your-password;TrustServerCertificate=yes" \
  --force
```

The script will:
1. Connect to your Microsoft SQL Server instance
2. Create all tables using `schema_mssql.sql`
3. Create indexes
4. Verify the setup

## Schema Differences

The Microsoft SQL Server schema is defined in `schema_mssql.sql`.

## Verification

After initialization, verify the tables were created:

```python
from database.db_manager import DatabaseManager
import config

db = DatabaseManager()
tables = db.execute_query("""
    SELECT TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
    ORDER BY TABLE_NAME
""")
print([t['TABLE_NAME'] for t in tables])
```

## Running the Application

Once configured, run the application normally:

```bash
python app.py
```

The application uses the Microsoft SQL Server connection configured in environment variables or `MSSQL_CONNECTION_STRING`.

## Troubleshooting

### "pyodbc not found"
```bash
pip install pyodbc
```

### "ODBC Driver not found"
- Install the ODBC Driver for SQL Server from Microsoft
- Verify the driver name matches what's in your connection string
- List available drivers: `pyodbc.drivers()` in Python

### Connection timeout
- Verify the server is accessible from your machine
- Check firewall settings
- Verify SQL Server is configured to accept TCP/IP connections
- Check the port number (default is 1433)

### Authentication errors
- Verify username and password
- For Windows Authentication, use: `Trusted_Connection=yes` instead of `UID` and `PWD`
- Example: `DRIVER={ODBC Driver 18 for SQL Server};SERVER=server;DATABASE=HaploSearch;Trusted_Connection=yes;TrustServerCertificate=yes`

### Table creation errors
- Ensure you have sufficient permissions (CREATE TABLE, CREATE INDEX)
- Check if tables already exist (use `--force` to drop and recreate)

## Notes

- **Data Migration**: This setup only creates the schema structure. Data migration from older local databases should be handled with a purpose-built migration script if needed.
- **Performance**: Microsoft SQL Server supports larger shared datasets and production deployment better than local file-based development databases.

## Docker Deployment

For Docker deployments, set environment variables in `docker-compose.yml`:

```yaml
services:
  haplosearch:
    environment:
      - MSSQL_SERVER=your-mssql-server
      - MSSQL_DATABASE=HaploSearch
      - MSSQL_USER=your-username
      - MSSQL_PASSWORD=your-password
      - MSSQL_DRIVER=ODBC Driver 18 for SQL Server
      - MSSQL_TRUST_SERVER_CERTIFICATE=true
```

Make sure the Docker container can reach your Microsoft SQL Server instance (network configuration, firewall rules, etc.).
