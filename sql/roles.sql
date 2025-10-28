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
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'obyra_migrator') THEN
    CREATE ROLE obyra_migrator LOGIN PASSWORD 'REEMPLAZAR_OBYRA_MIGRATOR_PASSWORD';
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

ALTER ROLE app_owner      SET search_path = app, public;
ALTER ROLE app_rw         SET search_path = app, public;
ALTER ROLE obyra_migrator SET search_path = app, public;
ALTER ROLE app_ro         SET search_path = app, public;

-- 4) Permisos por defecto en esquema
GRANT USAGE ON SCHEMA app TO app_rw, app_ro, obyra_migrator;
GRANT CREATE ON SCHEMA app TO obyra_migrator;

ALTER DEFAULT PRIVILEGES FOR ROLE obyra_migrator IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE obyra_migrator IN SCHEMA app GRANT SELECT ON TABLES TO app_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE obyra_migrator IN SCHEMA app GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO app_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE obyra_migrator IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO app_ro;

-- 5) Extensiones (si tu proveedor las permite)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 6) Tabla de versionado de seeds (idempotente)
CREATE TABLE IF NOT EXISTS app.seed_version (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE app.seed_version OWNER TO app_owner;
GRANT SELECT, INSERT ON app.seed_version TO app_rw;
GRANT SELECT ON app.seed_version TO app_ro;
GRANT USAGE, SELECT, UPDATE ON SEQUENCE app.seed_version_id_seq TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE app.seed_version_id_seq TO app_ro;

COMMIT;
