# Migraciones y Seeds – OBYRA

## Migraciones (Alembic / Flask-Migrate)
- Exportar variables (Windows PowerShell):
  ```powershell
  $env:ALEMBIC_DATABASE_URL="postgresql+psycopg://obyra_migrator:<PASS>@localhost:5435/obyra_dev"
  ```
- Ver estado actual: `alembic current`
- Historial completo: `alembic history --verbose`
- Generar desde modelos: `flask db migrate -m "YYYYMMDD_hhmm_descriptivo"`
- Crear baseline vacío: `alembic revision --empty -m "baseline"`
- Aplicar: `alembic upgrade head`
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

CI/CD usa DATABASE_URL_MIGRATOR (rol obyra_migrator) para migraciones.

SSL: usar sslmode=require en hosts administrados.
