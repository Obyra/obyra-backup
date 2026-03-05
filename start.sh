#!/bin/bash
flask db upgrade || echo "Warning: migration failed, continuing..."
exec gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120
