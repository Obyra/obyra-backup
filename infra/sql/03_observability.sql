-- Observabilidad para PostgreSQL 16
-- Debe ejecutarse con privilegios de superusuario

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

COMMENT ON EXTENSION pg_stat_statements IS 'Habilitado para monitorear consultas de OBYRA';

-- Ajustes recomendados (aplicar vía parámetro del proveedor si es posible)
-- pg_stat_statements.max = 10000
-- pg_stat_statements.track = all
-- shared_preload_libraries += 'pg_stat_statements'

-- Nota: Los parámetros anteriores suelen configurarse a nivel del servicio administrado.
