# OBYRA IA — Guía de Entorno (DEV / Staging)

## Flask / Runtime
FLASK_APP=app.py
FLASK_RUN_PORT=8080
FLASK_ENV=development
FLASK_DEBUG=1
PYTHONIOENCODING=utf-8

## Seguridad
SECRET_KEY=(generar con: python -c "import secrets; print(secrets.token_urlsafe(32))")
SESSION_SECRET=${SECRET_KEY}
AUTO_CREATE_DB=0

## Base de datos (PostgreSQL + psycopg3)
# Contenedor local (host 5433 → contenedor 5432):
docker run --name obyra-pg -p 5433:5432 -e POSTGRES_USER=obyra -e POSTGRES_PASSWORD=obyra -e POSTGRES_DB=obyra_dev -d postgres:16

# Cadena de conexión (para .env)
DATABASE_URL=postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev

## Feature Flags
WIZARD_BUDGET_BREAKDOWN_ENABLED=false
WIZARD_BUDGET_SHADOW_MODE=true
SHOW_IA_CALCULATOR_BUTTON=false
ENABLE_REPORTS=1
ENABLE_GOOGLE_OAUTH_HELP=true

## Mercado Pago (DEV)
MP_ACCESS_TOKEN=
MP_WEBHOOK_PUBLIC_URL=http://127.0.0.1:8080/api/market/payments/mp/webhook

## SMTP (Mailtrap u otro)
SMTP_HOST=smtp.mailtrap.io
SMTP_PORT=2525
SMTP_USER=da98bc77454079
SMTP_PASS=4ff4b6c3927ecb
SMTP_PASSWORD=${SMTP_PASS}
SMTP_USE_TLS=1
FROM_EMAIL=OBYRA IA <no-reply@obyra.local>
MAIL_FROM=${FROM_EMAIL}

## Mapas / Geocoding
MAPS_PROVIDER=nominatim
MAPS_API_KEY=
MAPS_USER_AGENT=obyra-dev-bot
GEOCODE_CACHE_TTL=3600

## Tipos de cambio
FX_PROVIDER=bna
EXCHANGE_FALLBACK_RATE=0

## IA / OpenAI (opcional)
OPENAI_API_KEY=

## Negocio
PLATFORM_COMMISSION_RATE=0.02

## Archivos / URLs
STORAGE_DIR=./storage
BASE_URL=http://127.0.0.1:8080
APP_BASE_URL=${BASE_URL}
