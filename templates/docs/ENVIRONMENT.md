OBYRA IA — Entorno Mínimo Viable
1. Prerrequisitos

Python 3.11+

PostgreSQL 16 (en desarrollo vía Docker)

WeasyPrint en Windows: MSYS2/MINGW64 instalado y en PATH

2. Variables de Entorno
Variable	Dev (Ejemplo)	Staging/Prod	Notas
FLASK_APP	app.py	app.py	Módulo principal
FLASK_ENV	development	production	Sin debugger en prod
FLASK_RUN_PORT	8080	a definir	Puerto HTTP
SECRET_KEY	generar	generar	python -c "import secrets; print(secrets.token_hex(32))"
DATABASE_URL	postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev	postgresql+psycopg://USER:PASS@HOST:PORT/DB	Usa Psycopg v3
OPENAI_API_KEY	opcional	sk-…	Calculadora IA
GOOGLE_OAUTH_CLIENT_ID	opcional	…apps.googleusercontent.com	Login con Google
GOOGLE_OAUTH_CLIENT_SECRET	opcional	…	Login con Google
MP_ACCESS_TOKEN	opcional	APP_USR-…	Token de Mercado Pago (nombre esperado por la app)

⚠️ Importante: No commitees SECRET_KEY, API keys ni passwords. Usá .env en local o variables de entorno en el servidor.

3. .env de ejemplo (solo desarrollo)
FLASK_APP=app.py
FLASK_ENV=development
FLASK_RUN_PORT=8080

# Generar con: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=REEMPLAZAR_CON_TOKEN_HEX_DE_64_CARACTERES

DATABASE_URL=postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev

# Opcionales
# OPENAI_API_KEY=sk-...
# GOOGLE_OAUTH_CLIENT_ID=...
# GOOGLE_OAUTH_CLIENT_SECRET=...
# MP_ACCESS_TOKEN=APP_USR-...

4. PostgreSQL 16 en Docker (Desarrollo)
Levantar el contenedor
docker run -d --name obyra-pg \
  -e POSTGRES_USER=obyra \
  -e POSTGRES_PASSWORD=obyra \
  -e POSTGRES_DB=obyra_dev \
  -p 5433:5432 \
  -v obyra-pgdata:/var/lib/postgresql/data \
  postgres:16

Verificar que está corriendo
docker ps --filter "name=obyra-pg"

URL de conexión (usada en dev)
postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev
