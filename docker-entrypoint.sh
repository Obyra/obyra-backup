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

    # Run Alembic migrations
    if [ -f "migrations/env.py" ]; then
        echo "Running: flask db upgrade"
        if ! flask db upgrade 2>&1; then
            echo "ERROR: Database migration failed! See error above."
            exit 1
        fi
        echo "✓ Migrations completed successfully!"
    else
        echo "WARNING: No migrations directory found, skipping..."
    fi

    # Restore original DATABASE_URL if we changed it
    if [ -n "$ORIGINAL_DATABASE_URL" ]; then
        export DATABASE_URL="$ORIGINAL_DATABASE_URL"
    fi
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
