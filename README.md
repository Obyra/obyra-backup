# OBYRA

## Base de datos

### Comandos locales
- `make db.up`: levanta un contenedor PostgreSQL 16 en `localhost:5433` (configurable vía `DB_PORT`).
- `make db.provision`: aplica `infra/sql/01_*.sql`, `02_*.sql` y `03_*.sql` sobre la base indicada de forma idempotente.
- `make db.migrate`: ejecuta `alembic upgrade head` usando `ALEMBIC_DATABASE_URL` (o `DATABASE_URL` si no está definido).
- `make db.reset.local`: ejecuta `alembic downgrade base && alembic upgrade head` para verificar migraciones localmente.

### Variables de entorno
Configura estas variables en tu entorno o archivo `.env`:

| Variable | Uso | Notas |
| --- | --- | --- |
| `DATABASE_URL` | Conexión estándar de la app (psycopg v3 + SQLAlchemy) | Ejemplo local: `postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev` |
| `ALEMBIC_DATABASE_URL` | Ejecutar migraciones y seeds estructurales | Usa el rol `obyra_migrator` en staging/prod. Si no está, Alembic utilizará `DATABASE_URL`. |
| `READONLY_DATABASE_URL` | Consultas analíticas o servicios de solo lectura | Apunta a replica/pooler de lectura. Opcional en local. |

### Flujo local recomendado
1. `make db.up`
2. `make db.provision`
3. `alembic history` para revisar estado.
4. `make db.migrate` para aplicar migraciones.
5. Verificar tablas en el esquema `app` con `psql postgresql://obyra:obyra@localhost:5433/obyra_dev -c "\\dt app.*"`.
6. Ejecutar tests de la aplicación según corresponda.

#### Windows (PowerShell)
Si no cuentas con `make`, puedes replicar los pasos anteriores así:

```powershell
# 1) Levantar Postgres 16 aislado en el puerto 5434
docker run --name obyra-pg-2 -e POSTGRES_USER=migrator -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=obyra_dev -p 5434:5432 -d postgres:16

# 2) Provisionar esquema, roles y observabilidad (usar here-strings no expandibles)
@'
\i infra/sql/01_schemas_roles.sql
\i infra/sql/02_grants.sql
\i infra/sql/03_observability.sql
'@ | docker exec -i obyra-pg-2 psql -v ON_ERROR_STOP=1 -U migrator -d obyra_dev -f -

# 3) Ejecutar Alembic (requiere ALEMBIC_DATABASE_URL definido)
@'
import alembic.config

alembic.config.main(['upgrade', 'head'])
'@
| python -
```

Consulta también la documentación específica en `docs/db/` para topología, políticas de migraciones, backups y checklists operativos.

> El rol que utilice Alembic debe tener privilegios `USAGE` y `CREATE` sobre el esquema `app`. Ejecuta `infra/sql/01_schemas_roles.sql` y `02_grants.sql` para garantizarlos.

### Troubleshooting
- **`SET ROLE` falla en entornos antiguos:** crear temporalmente el rol `obyra_migrator` y volver a ejecutar `02_grants.sql`.
- **Alembic quedó con estado inconsistente:** usar `alembic stamp base` para resetear y luego `alembic upgrade head`.
- **`alembic_version` existe en `public`:** `BEGIN; ALTER TABLE public.alembic_version SET SCHEMA app; COMMIT;` y re-ejecutar `alembic upgrade head`.
- **Necesito limpiar completamente el contenedor local:** `docker rm -f obyra-pg` y volver a correr `make db.up && make db.provision`.
