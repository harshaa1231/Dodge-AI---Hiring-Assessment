#!/bin/bash
# start.sh — Backend startup script for Render
# Builds DB if needed, then starts the server

set -e

echo "=== O2C Graph Query System ==="

# Build database if it doesn't exist
if [ ! -f "./data/o2c.db" ]; then
    echo "Building SQLite database..."
    python db.py --data-dir "${DATA_DIR:-./sap-o2c-data}" --db-path "${DB_PATH:-./data/o2c.db}"
    echo "Database built."
else
    echo "Database already exists, skipping build."
fi

# Start FastAPI
echo "Starting server on port ${PORT:-8000}..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
