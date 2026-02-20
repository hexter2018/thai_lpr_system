#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
while ! pg_isready -h postgres -p 5432 -U lpr; do
    sleep 1
done
echo "✓ PostgreSQL is ready"

echo "Initializing database..."
python init_db.py

echo "Starting FastAPI server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
