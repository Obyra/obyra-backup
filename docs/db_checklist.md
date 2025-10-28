# Checklist de Acceso y Seguridad – DB OBYRA

## Conexión y roles
[ ] La app usa rol `app_rw`
[ ] CI/CD usa rol `obyra_migrator` sólo para migraciones
[ ] Existe rol `app_ro` para lecturas/BI
[ ] Esquema `app` creado y con `app_owner` como owner
[ ] `sslmode=require` en `DATABASE_URL` cuando aplique

## Secrets
[ ] `DATABASE_URL` (app_rw) en GitHub Secrets
[ ] `DATABASE_URL_MIGRATOR` (obyra_migrator) en GitHub Secrets
[ ] `.env` local define `ALEMBIC_DATABASE_URL` con rol `obyra_migrator`
[ ] Rotación de credenciales cada 90 días documentada

## Migraciones y seeds
[ ] Workflow de migraciones documentado (Alembic/Flask-Migrate)
[ ] Convención `YYYYMMDD_hhmm_descriptivo.py`
[ ] Tabla `app.seed_version` creada y seeds registrados
[ ] CLI de seeds probado en Dev

## Backups y restore
[ ] Backups diarios habilitados (Prod)
[ ] Retención 30 días (Prod) / 7 días (Stg)
[ ] Ensayo de restauración verificado este mes

## Observabilidad
[ ] Alertas por conexiones/espacio/latencia
[ ] Métricas expuestas y visibles (conexiones, p95, deadlocks)

## Auditoría rápida
[ ] Nadie usa superusuario en la app
[ ] No hay `db.create_all()` en runtime
[ ] Accesos limitados por IP/seguridad del proveedor
