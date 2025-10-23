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

## Configuración de base de datos local

1. Reinicia el contenedor de Postgres para partir de una base limpia:

   ```bash
   docker compose down --volumes
   docker compose up -d db
   ```

2. Exporta las variables necesarias y aplica las migraciones desde cero:

   ```bash
   export FLASK_APP=wsgi.py
   export DATABASE_URL="postgresql+psycopg://obyra:postgres@localhost:5432/obyra_dev?sslmode=disable"
   flask db upgrade
   ```

3. Verifica que todos los objetos estén en el esquema `app`:

   ```sql
   SELECT table_schema, table_name
   FROM information_schema.tables
   WHERE table_schema = 'app'
   ORDER BY table_name;

   SELECT n.nspname AS schema, t.typname AS type
   FROM pg_type t
   JOIN pg_namespace n ON n.oid = t.typnamespace
   WHERE n.nspname = 'app' AND t.typtype = 'e'
   ORDER BY t.typname;
   ```

   Debes ver las tablas de negocio (incluida `inventory_category`) y los tipos ENUM creados en `app`, junto a la tabla `app.alembic_version` con la versión más reciente.

## Migraciones Alembic

Comandos disponibles:

```bash
flask db revision -m "mensaje"
flask db upgrade
flask db downgrade
```

La tabla `alembic_version` vive en el esquema `app`. Las migraciones de seeds deben ser idempotentes utilizando `INSERT ... ON CONFLICT DO UPDATE`.

## Scripts útiles

```bash
flask db upgrade
flask fx update
flask cac set --value 123.45
flask seed:inventario --global
```

## TLS en producción

Configura la URL de base de datos con `sslmode=require` (o `verify-full` si cuentas con CA y hostname válidos). Para entornos donde TLS no está disponible (por ejemplo, desarrollo local), establece `DB_SSLMODE=disable` antes de inicializar la aplicación.
