# OBYRA

## Base de datos

### Comandos locales
- `make db.up`: levanta un contenedor PostgreSQL 16 en `localhost:5433` con esquema `app` asegurado.
- `make db.migrate`: ejecuta `alembic upgrade head` usando `ALEMBIC_DATABASE_URL` (o `DATABASE_URL` si no está definido).
- `make db.reset.local`: elimina el contenedor local y lo vuelve a crear desde cero.

### Variables de entorno
Configura estas variables en tu entorno o archivo `.env`:

| Variable | Uso | Notas |
| --- | --- | --- |
| `DATABASE_URL` | Conexión estándar de la app (psycopg v3 + SQLAlchemy) | Ejemplo local: `postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev` |
| `ALEMBIC_DATABASE_URL` | Ejecutar migraciones y seeds estructurales | Usa el rol `obyra_migrator` en staging/prod. Si no está, Alembic utilizará `DATABASE_URL`. |
| `READONLY_DATABASE_URL` | Consultas analíticas o servicios de solo lectura | Apunta a replica/pooler de lectura. Opcional en local. |

### Flujo local recomendado
1. `make db.up`
2. `alembic history` para revisar estado.
3. `make db.migrate` para aplicar migraciones.
4. Verificar tablas en el esquema `app` con `psql postgresql://obyra:obyra@localhost:5433/obyra_dev -c "\dt app.*"`.
5. Ejecutar tests de la aplicación según corresponda.

Consulta también la documentación específica en `docs/db/` para topología, políticas de migraciones, backups y checklists operativos.
