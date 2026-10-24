#!/bin/sh
set -e

echo "[entrypoint] Seeding SQLite database..."
python scripts/init_db.py

echo "[entrypoint] Building FAISS index (first run may download embedding model)..."
python scripts/build_index.py

echo "[entrypoint] Starting API on 0.0.0.0:8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
