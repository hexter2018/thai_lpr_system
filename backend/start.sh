#!/usr/bin/env bash
set -euo pipefail

echo "[backend] waiting for postgres..."
python - <<'PY'
import os, time
import psycopg2
from urllib.parse import urlparse

url = os.getenv("DATABASE_URL")
# url like: postgresql+psycopg2://user:pass@host:port/db
url2 = url.replace("postgresql+psycopg2://", "postgresql://")
p = urlparse(url2)
for i in range(60):
    try:
        conn = psycopg2.connect(
            dbname=p.path.lstrip("/"),
            user=p.username,
            password=p.password,
            host=p.hostname,
            port=p.port or 5432,
        )
        conn.close()
        print("[backend] postgres is ready")
        break
    except Exception as e:
        time.sleep(1)
else:
    raise SystemExit("[backend] postgres not ready")
PY

echo "[backend] applying migrations..."
alembic upgrade head

echo "[backend] starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
