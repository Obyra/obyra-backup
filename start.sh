#!/bin/bash

# Arranca gunicorn en background para que el healthcheck pase de inmediato
gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120 &
GUNICORN_PID=$!

# Espera 45s para que Railway mate el contenedor viejo (que tenia los locks de DB)
# y luego corre la migracion sin contention
(
    sleep 45
    echo "Running migrations after stabilization..."
    flask db upgrade || (sleep 10 && flask db upgrade) || echo "Migration failed after retry"
) &

# Mantiene el proceso vivo hasta que gunicorn termine
wait $GUNICORN_PID
