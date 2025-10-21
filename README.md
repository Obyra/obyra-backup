# OBYRA Platform

## Configuración rápida

1. Crea un archivo `.env` basado en [.env.example](./.env.example). Asegúrate de definir `DATABASE_URL` con el driver `postgresql+psycopg` y el parámetro `sslmode` adecuado (`require` o `verify-full`).
2. Ajusta los parámetros del pool mediante `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE` y `DB_POOL_PRE_PING`.
3. Exporta `FLASK_APP=wsgi.py` para que los comandos de Flask utilicen la fábrica `create_app()`.
4. Ejecuta las migraciones con `flask db upgrade` usando el usuario **migrator** (en producción también debe usar TLS).
5. Arranca la aplicación (`flask run` o `gunicorn wsgi:app`).

## Docker Compose de desarrollo

```
docker compose up --build app
```

El servicio `app` aplica las migraciones (`flask db upgrade`) contra el contenedor PostgreSQL antes de levantar `gunicorn`. Para conexiones locales sin TLS, exporta `DB_SSLMODE=disable` (en producción debe ser `require` o `verify-full`).

## Migraciones Alembic

Comandos disponibles:

```bash
flask db revision -m "mensaje"
flask db upgrade
flask db downgrade
```

La tabla `alembic_version` vive en el esquema `ops`, mientras que los objetos de negocio residen en el esquema `core`. Las migraciones de seeds deben ser idempotentes utilizando `INSERT ... ON CONFLICT DO UPDATE`.

## Scripts útiles

```bash
flask db upgrade
flask fx update
flask cac set --value 123.45
flask seed:inventario --global
```

## TLS en producción

Configura la URL de base de datos con `sslmode=require` (o `verify-full` si cuentas con CA y hostname válidos). Para entornos donde TLS no está disponible (por ejemplo, desarrollo local), establece `DB_SSLMODE=disable` antes de inicializar la aplicación.
