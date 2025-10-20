-- OBYRA – Roles, esquema y permisos base
-- Ejecutar con un user administrador (p.ej. postgres) en cada base: obyra_dev / obyra_stg / obyra_prod

BEGIN;

-- 1) Esquema
CREATE SCHEMA IF NOT EXISTS app;

-- 2) Roles (cambiar contraseñas en los entornos reales)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_owner') THEN
    CREATE ROLE app_owner NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_admin') THEN
    CREATE ROLE app_admin LOGIN PASSWORD 'REEMPLAZAR_APP_ADMIN_PASSWORD';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_rw') THEN
    CREATE ROLE app_rw LOGIN PASSWORD 'REEMPLAZAR_APP_RW_PASSWORD';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_ro') THEN
    CREATE ROLE app_ro LOGIN PASSWORD 'REEMPLAZAR_APP_RO_PASSWORD';
  END IF;
END
$$;

-- 3) Ownership
ALTER SCHEMA app OWNER TO app_owner;

-- 4) Permisos por defecto en esquema
GRANT USAGE ON SCHEMA app TO app_admin, app_rw, app_ro;

ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT ON TABLES TO app_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO app_ro;

-- 5) Extensiones (si tu proveedor las permite)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 6) Tabla de versionado de seeds (idempotente)
CREATE TABLE IF NOT EXISTS app.seed_version (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
