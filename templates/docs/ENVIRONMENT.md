# OBYRA IA — Entorno mínimo viable

## 1) Prerrequisitos
- **Python** 3.11+
- **PostgreSQL 16** (en dev usamos Docker)
- **WeasyPrint** nativo en Windows (MSYS2/MINGW64 instalado y en `PATH`)

---

## 2) Variables de entorno (dev / staging / prod)

| Variable                      | Dev (ejemplo)                                                | Staging/Prod (formato)                        | Notas                                               |
|------------------------------|--------------------------------------------------------------|-----------------------------------------------|-----------------------------------------------------|
| `FLASK_APP`                  | `app.py`                                                     | `app.py`                                      | Módulo principal                                    |
| `FLASK_ENV`                  | `development`                                                | `production`                                  | En prod, sin debugger                               |
| `FLASK_RUN_PORT`             | `8080`                                                       | *a definir*                                   | Puerto HTTP                                         |
| `SECRET_KEY`                 | *generar*                                                    | *generar*                                     | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL`               | `postgresql+psycopg://obyra:obyra@localhost:5435/obyra_dev` | `postgresql+psycopg://USER:PASS@HOST:PORT/DB` | Usa Psycopg v3                                      |
| `OPENAI_API_KEY`             | *(opcional)*                                                 | `sk-…`                                        | Para calculadora IA                                 |
| `GOOGLE_OAUTH_CLIENT_ID`     | *(opcional)*                                                 | `…apps.googleusercontent.com`                 | Login con Google                                    |
| `GOOGLE_OAUTH_CLIENT_SECRET` | *(opcional)*                                                 | `…`                                           |                                                     |
| `MERCADOPAGO_ACCESS_TOKEN`   | *(opcional)*                                                 | `APP_USR-…`                                   | Marketplace                                         |

> **Nunca** commitear `SECRET_KEY`, API keys ni passwords. Usar `.env` en local o variables de entorno en el servidor.

---

## 3) `.env` de ejemplo (solo desarrollo)

```ini
FLASK_APP=app.py
FLASK_ENV=development
FLASK_RUN_PORT=8080
SECRET_KEY=REEMPLAZAR_CON_un_token_hex_de_64
DATABASE_URL=postgresql+psycopg://obyra:obyra@localhost:5435/obyra_dev
# Agregar "?sslmode=require" si el host administrado lo exige.

# Opcionales
# OPENAI_API_KEY=sk-...
# GOOGLE_OAUTH_CLIENT_ID=...
# GOOGLE_OAUTH_CLIENT_SECRET=...
# MERCADOPAGO_ACCESS_TOKEN=APP_USR-...

# Crear/levantar Postgres 16 en el puerto 5435
docker run -d --name obyra-pg-stg \
  -e POSTGRES_USER=obyra \
  -e POSTGRES_PASSWORD=obyra \
  -e POSTGRES_DB=obyra_dev \
  -p 5435:5432 \
  -v obyra-pg-stg-data:/var/lib/postgresql/data \
  postgres:16

# Verificar que está corriendo
docker ps --filter "name=obyra-pg-stg"

postgresql+psycopg://obyra:obyra@localhost:5435/obyra_dev
```
