#!/bin/bash
set -e

# ============================================
# Activate virtual environment
# ============================================
export PATH="/opt/venv/bin:$PATH"

echo "==========================================="
echo "OBYRA Flask App - Docker Entrypoint"
echo "==========================================="

# ============================================
# 1. Wait for PostgreSQL to be ready
# ============================================
if [ -n "$DATABASE_URL" ]; then
    echo "Waiting for PostgreSQL to be ready..."

    # Docker-compose healthchecks ensure dependencies are ready
    # But we'll add a small grace period for stability
    sleep 2

    echo "✓ PostgreSQL dependency satisfied!"
else
    echo "WARNING: DATABASE_URL not set, skipping database check"
fi

# ============================================
# 2. Run Database Migrations (if enabled)
# ============================================
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "==========================================="
    echo "Running database migrations..."
    echo "==========================================="

    # Check if we should use ALEMBIC_DATABASE_URL (migrator role)
    if [ -n "$ALEMBIC_DATABASE_URL" ]; then
        echo "Using ALEMBIC_DATABASE_URL for migrations (migrator role)"
        export DATABASE_URL="$ALEMBIC_DATABASE_URL"
    fi

    # Ensure schema "app" exists (requerido por migraciones Alembic que lo usan).
    # En entornos reales este schema lo crea sql/roles.sql; en dev Docker
    # no ejecutamos ese script, así que lo creamos acá.
    # Idempotente: CREATE SCHEMA IF NOT EXISTS no falla en re-runs.
    echo "Ensuring schema 'app' exists..."
    python - <<'PYEOF' || echo "WARNING: could not ensure schema 'app' (DB unreachable?)"
import os
from sqlalchemy import create_engine, text
url = os.environ.get('DATABASE_URL')
if url:
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS app'))
    print("OK: schema 'app' ensured")
PYEOF

    # Run Alembic migrations
    if [ -f "migrations/env.py" ]; then
        echo "Running: flask db upgrade"
        # Skip runtime_migrations durante el upgrade: Alembic importa app.py
        # para descubrir modelos y los ALTER TABLE fallan si las tablas aún
        # no existen. Runtime migrations corren después, en el arranque de gunicorn.
        export SKIP_RUNTIME_MIGRATIONS=1
        if ! flask db upgrade 2>&1; then
            echo "WARNING: Database migration failed! See error above."
            # En Railway, no salimos con error porque db.create_all() en app.py
            # creará las tablas. Las migraciones locales usan schema "app" que
            # no existe en Railway.
            if [ -n "$RAILWAY_ENVIRONMENT" ] || [ -n "$RAILWAY_PROJECT_ID" ]; then
                echo "Railway detected: continuing despite migration failure (db.create_all will handle tables)"
            else
                echo "ERROR: Database migration failed!"
                exit 1
            fi
        else
            echo "✓ Migrations completed successfully!"
        fi
    else
        echo "WARNING: No migrations directory found, skipping..."
    fi

    # Restore original DATABASE_URL if we changed it
    if [ -n "$ORIGINAL_DATABASE_URL" ]; then
        export DATABASE_URL="$ORIGINAL_DATABASE_URL"
    fi

    # Permitir que runtime_migrations corran en el arranque normal de gunicorn
    unset SKIP_RUNTIME_MIGRATIONS
else
    echo "Skipping migrations (RUN_MIGRATIONS=false)"
fi

# ============================================
# 3. Create necessary directories
# ============================================
echo "==========================================="
echo "Setting up application directories..."
echo "==========================================="

mkdir -p /app/instance /app/storage /app/reports /app/logs
echo "✓ Directories created"

# ============================================
# 4. Execute the command passed to the script
# ============================================
echo "==========================================="
echo "Starting application..."
echo "==========================================="
echo "Command: $@"
echo "==========================================="

exec "$@"
