#!/bin/bash
set -e

echo "Running migrations..."
flask db upgrade || (echo "Migration failed, retrying in 15s..." && sleep 15 && flask db upgrade)

echo "Starting gunicorn..."
exec gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120 --preload
