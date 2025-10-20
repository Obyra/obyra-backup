# Migraciones y Seeds – OBYRA

## Migraciones (Alembic / Flask-Migrate)
- Generar: `flask db migrate -m "YYYYMMDD_hhmm_descriptivo"`
- Aplicar: `flask db upgrade`
- No modificar migraciones ya aplicadas en producción.
- Revisar `downgrade()` cuando aplique.

## Seeds
- Registra un seed en `app.seed_version` para idempotencia.
- Inventario: `flask seed:inventario --global` o `--org "NOMBRE_ORG"`
- Registra manualmente en `app.seed_version`:
  ```sql
  INSERT INTO app.seed_version (name) VALUES ('2025-01-10_inventario_global');

Roles/Conexión

App usa DATABASE_URL con rol app_rw.

CI/CD usa DATABASE_URL_ADMIN (rol app_admin) para migraciones.

SSL: usar sslmode=require en hosts administrados.
