-- Observabilidad para PostgreSQL 16.
-- Seguro para ejecutarse múltiples veces y en proveedores administrados (puede emitir NOTICE si la extensión no está permitida).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') THEN
        EXECUTE 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements';
    END IF;
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'pg_stat_statements no se pudo habilitar (privilegios insuficientes). Revisar configuración del proveedor.';
    WHEN feature_not_supported THEN
        RAISE NOTICE 'pg_stat_statements no está disponible en este servicio. Documentar la limitación.';
END
$$;

COMMENT ON EXTENSION pg_stat_statements IS 'Habilitado para monitorear consultas de OBYRA';

-- Ajustes recomendados (aplicar vía parámetro del proveedor si es posible)
-- pg_stat_statements.max = 10000
-- pg_stat_statements.track = all
-- shared_preload_libraries += ''pg_stat_statements''

-- Validación manual: SELECT calls, total_time FROM pg_stat_statements ORDER BY total_time DESC LIMIT 5;
