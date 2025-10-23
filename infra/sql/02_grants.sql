-- Permisos detallados por rol para el esquema app
-- Ejecutar después de 01_schemas_roles.sql y una vez creadas las tablas

-- Permisos generales para la aplicación
GRANT CONNECT ON DATABASE obyra_dev TO obyra_app;
GRANT CONNECT ON DATABASE obyra_dev TO obyra_migrator;
GRANT CONNECT ON DATABASE obyra_dev TO obyra_readonly;

-- Permisos sobre objetos existentes
DO $$
DECLARE
    obj RECORD;
BEGIN
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
END$$;

-- Permisos por defecto para objetos futuros
ALTER DEFAULT PRIVILEGES FOR ROLE obyra_migrator IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO obyra_app;
ALTER DEFAULT PRIVILEGES FOR ROLE obyra_migrator IN SCHEMA app
    GRANT SELECT ON TABLES TO obyra_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE obyra_migrator IN SCHEMA app
    GRANT USAGE, SELECT ON SEQUENCES TO obyra_app;
ALTER DEFAULT PRIVILEGES FOR ROLE obyra_migrator IN SCHEMA app
    GRANT SELECT ON SEQUENCES TO obyra_readonly;
