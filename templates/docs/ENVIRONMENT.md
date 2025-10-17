# OBYRA IA — Entorno Mínimo Viable

## 1. Prerrequisitos

- **Python** 3.11+
- **PostgreSQL 16** (en desarrollo via Docker)
- **WeasyPrint** nativo en Windows (MSYS2/MINGW64 instalado en `PATH`)

---

## 2. Variables de Entorno

| Variable | Dev (Ejemplo) | Staging/Prod | Notas |
|----------|---|---|---|
| `FLASK_APP` | `app.py` | `app.py` | Módulo principal |
| `FLASK_ENV` | `development` | `production` | Sin debugger en prod |
| `FLASK_RUN_PORT` | `8080` | *a definir* | Puerto HTTP |
| `SECRET_KEY` | *generar* | *generar* | Usar: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | `postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev` | `postgresql+psycopg://USER:PASS@HOST:PORT/DB` | Psycopg v3 |
| `OPENAI_API_KEY` | *opcional* | `sk-…` | Para calculadora IA |
| `GOOGLE_OAUTH_CLIENT_ID` | *opcional* | `…apps.googleusercontent.com` | Login con Google |
| `GOOGLE_OAUTH_CLIENT_SECRET` | *opcional* | `…` | Login con Google |
| `MERCADOPAGO_ACCESS_TOKEN` | *opcional* | `APP_USR-…` | Marketplace |

**⚠️ IMPORTANTE:** Nunca commitear `SECRET_KEY`, API keys ni passwords. Usar `.env` en local o variables de entorno en servidor.

---

## 3. Archivo `.env` de Ejemplo (Desarrollo)

```ini
FLASK_APP=app.py
FLASK_ENV=development
FLASK_RUN_PORT=8080
SECRET_KEY=REEMPLAZAR_CON_TOKEN_HEX_DE_64_CARACTERES
DATABASE_URL=postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev

# Opcionales
# OPENAI_API_KEY=sk-...
# GOOGLE_OAUTH_CLIENT_ID=...
# GOOGLE_OAUTH_CLIENT_SECRET=...
# MERCADOPAGO_ACCESS_TOKEN=APP_USR-...
```

---

## 4. PostgreSQL 16 en Docker (Desarrollo)

### Levantar el contenedor

```bash
docker run -d --name obyra-pg \
  -e POSTGRES_USER=obyra \
  -e POSTGRES_PASSWORD=obyra \
  -e POSTGRES_DB=obyra_dev \
  -p 5433:5432 \
  -v obyra-pgdata:/var/lib/postgresql/data \
  postgres:16
```

### Verificar que está corriendo

```bash
docker ps --filter "name=obyra-pg"
```

### URL de conexión (usada en dev)

```
postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev
```