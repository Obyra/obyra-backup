-- Permisos detallados por rol para el esquema app.
-- Ejecutar después de 01_schemas_roles.sql y una vez creadas las tablas necesarias.

DO $$
DECLARE
    target_db text := current_database();
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO obyra_app', target_db);
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO obyra_migrator', target_db);
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO obyra_readonly', target_db);
END
$$;

-- Permitir que el rol migrator gestione objetos dentro del esquema app.
GRANT USAGE, CREATE ON SCHEMA app TO obyra_migrator;

DO $$
DECLARE
    obj RECORD;
    previous_role text := current_setting('role', true);
BEGIN
    -- Ejecutar el resto con privilegios del owner del esquema.
    PERFORM set_config('role', 'obyra_migrator', true);

    FOR obj IN SELECT tablename FROM pg_tables WHERE schemaname = 'app'
    LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE app.%I TO obyra_app', obj.tablename);
        EXECUTE format('GRANT SELECT ON TABLE app.%I TO obyra_readonly', obj.tablename);
        EXECUTE format('ALTER TABLE app.%I OWNER TO obyra_migrator', obj.tablename);
    END LOOP;

    FOR obj IN SELECT sequencename FROM pg_sequences WHERE schemaname = 'app'
    LOOP
        EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE app.%I TO obyra_app', obj.sequencename);
        EXECUTE format('GRANT SELECT ON SEQUENCE app.%I TO obyra_readonly', obj.sequencename);
        EXECUTE format('ALTER SEQUENCE app.%I OWNER TO obyra_migrator', obj.sequencename);
    END LOOP;

    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO obyra_migrator';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO obyra_app';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT ON TABLES TO obyra_readonly';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE,SELECT ON SEQUENCES TO obyra_app';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT ON SEQUENCES TO obyra_readonly';

    IF COALESCE(previous_role, '') = '' THEN
        PERFORM set_config('role', '', true);
    ELSE
        PERFORM set_config('role', previous_role, true);
    END IF;
END
$$;

-- Si existe un rol local "migrator", asegurar permisos mínimos.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migrator') THEN
        EXECUTE 'GRANT USAGE, CREATE ON SCHEMA app TO migrator';
    END IF;
END
$$;
