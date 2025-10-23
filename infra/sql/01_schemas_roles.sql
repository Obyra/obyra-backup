-- Provisionamiento inicial de esquema y roles para OBYRA
-- Ejecutar con un rol administrador en PostgreSQL 16 (no requiere el rol "postgres").

-- Crear roles de aplicación si no existen.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'obyra_app') THEN
        EXECUTE 'CREATE ROLE obyra_app LOGIN PASSWORD ''REPLACE_ME_APP''';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'obyra_migrator') THEN
        EXECUTE 'CREATE ROLE obyra_migrator LOGIN PASSWORD ''REPLACE_ME_MIGRATOR''';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'obyra_readonly') THEN
        EXECUTE 'CREATE ROLE obyra_readonly LOGIN PASSWORD ''REPLACE_ME_READONLY''';
    END IF;
END
$$;

-- Crear esquema objetivo si no existe y transferir propiedad al rol migrator.
CREATE SCHEMA IF NOT EXISTS app;
ALTER SCHEMA app OWNER TO obyra_migrator;

-- Asegurar search_path consistente para todos los roles.
ALTER ROLE obyra_app SET search_path = app, public;
ALTER ROLE obyra_migrator SET search_path = app, public;
ALTER ROLE obyra_readonly SET search_path = app, public;

-- Permisos mínimos para acceder al esquema.
GRANT USAGE ON SCHEMA app TO obyra_app;
GRANT USAGE ON SCHEMA app TO obyra_readonly;
GRANT USAGE, CREATE ON SCHEMA app TO obyra_migrator;

-- Si existe un rol local "migrator" (desarrolladores), otorgar permisos equivalentes.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migrator') THEN
        EXECUTE 'GRANT USAGE, CREATE ON SCHEMA app TO migrator';
    END IF;
END
$$;

-- Documentación: ajustar contraseñas de los roles anteriores y revocar LOGIN en producción según política de seguridad.
