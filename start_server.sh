#!/bin/bash

# Configurar variables de entorno con el puerto correcto
export DATABASE_URL="postgresql+psycopg://obyra:obyra_dev_password@localhost:5436/obyra_dev"
export ALEMBIC_DATABASE_URL="postgresql+psycopg://obyra_migrator:migrator_dev_password@localhost:5436/obyra_dev"

echo "================================================"
echo "Iniciando servidor Flask con configuración local"
echo "================================================"
echo "DATABASE_URL: $DATABASE_URL"
echo "Puerto Flask: 5002"
echo "================================================"

# Activar virtualenv si existe
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✅ Virtualenv activado (.venv)"
elif [ -d "venv" ]; then
    source venv/bin/activate
    echo "✅ Virtualenv activado (venv)"
fi

# Iniciar el servidor Flask
python -m flask run --host=0.0.0.0 --port=5002 --debug
