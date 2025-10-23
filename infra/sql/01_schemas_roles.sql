-- Provisionamiento inicial de esquema y roles para OBYRA
-- Ejecutar con superusuario en PostgreSQL 16

CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION postgres;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'obyra_app') THEN
        CREATE ROLE obyra_app LOGIN PASSWORD 'REPLACE_ME_APP';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'obyra_migrator') THEN
        CREATE ROLE obyra_migrator LOGIN PASSWORD 'REPLACE_ME_MIGRATOR';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'obyra_readonly') THEN
        CREATE ROLE obyra_readonly LOGIN PASSWORD 'REPLACE_ME_READONLY';
    END IF;
END
$$;

ALTER ROLE obyra_app SET search_path = app, public;
ALTER ROLE obyra_migrator SET search_path = app, public;
ALTER ROLE obyra_readonly SET search_path = app, public;

-- El rol migrator es propietario del esquema
ALTER SCHEMA app OWNER TO obyra_migrator;

-- Permitir que la aplicación use el esquema app
GRANT USAGE ON SCHEMA app TO obyra_app;
GRANT USAGE ON SCHEMA app TO obyra_readonly;

-- Permitir que el rol migrator administre el esquema
GRANT ALL ON SCHEMA app TO obyra_migrator;
