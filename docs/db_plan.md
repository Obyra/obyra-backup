# Plan de Base de Datos – OBYRA

## Topología objetivo
- **Instancia por entorno:** `dev`, `stg`, `prod`.
- **Base por entorno:** `obyra_dev`, `obyra_stg`, `obyra_prod`.
- **Esquema principal:** `app`.
- **Extensiones requeridas:** `pgcrypto`, `uuid-ossp` (si aplica).
- **Conexiones:** SSL obligatorio (`sslmode=require` cuando sea hosted).

## Roles y privilegios
- `app_owner` (sin login): dueño del esquema y objetos.
- `obyra_migrator`: corre migraciones (DDL) y administra privilegios.
- `app_rw`: rol de la aplicación (lectura/escritura).
- `app_ro`: sólo lectura (BI/soporte).

**Principio de mínimo privilegio:**
- La app usa `app_rw`.
- Migraciones en CI/CD usan `obyra_migrator`.
- Consultas de reporting usan `app_ro`.

## Pooling y conexiones (SQLAlchemy / Flask)
- `pool_pre_ping: true`
- `pool_recycle: 1800`
- `pool_size/max_overflow` según entorno (prod > dev).
- `sslmode=require` si el host es administrado (p.ej. Neon/Cloud).

## Backups y restauración
- **Prod:** PITR + snapshot diario (retención 30 días).
- **Stg:** snapshot diario (retención 7 días).
- **Dev:** opcional (dump semanal).
- **Ensayo de restore:** mensual en Stg (obligatorio).

## Migraciones (Alembic / Flask-Migrate)
- Rama única `migrations/versions/`.
- **Convención de nombres:** `YYYYMMDD_hhmm_descriptivo.py`.
- **Reglas:**
  - No editar migraciones ya aplicadas en Prod.
  - Una migración por cambio lógico.
  - Revisar `downgrade()` cuando sea viable.

## Seeds (datos de arranque)
- Mantener **seed idempotente** y versionado.
- Crear tabla `app.seed_version` para registrar seeds aplicados.
- Usar CLI `flask seed:inventario --org ...` (ya disponible) y registrar ejecución.

## Seguridad y secretos
- `DATABASE_URL` (app_rw) y `DATABASE_URL_MIGRATOR` (obyra_migrator) en **GitHub Secrets** por entorno.
- Rotación de credenciales cada 90 días.
- Regla de firewall/SG: restringir IPs del runner/host.

## Observabilidad
- Alertas: conexiones activas, espacio en disco, latencia, errores de autovacuum.
- Métricas mínimas: conexiones, tiempo de query p95, deadlocks.
