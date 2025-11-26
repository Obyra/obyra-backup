-- Migración: Agregar campos de medición a etapas_obra
-- Fecha: 2025-11-26
-- Descripción: Permite registrar mediciones (m2, m3, ml) por etapa para calcular avance

-- Agregar campos de medición a la tabla etapas_obra
ALTER TABLE etapas_obra
ADD COLUMN IF NOT EXISTS unidad_medida VARCHAR(10) DEFAULT 'm2';

ALTER TABLE etapas_obra
ADD COLUMN IF NOT EXISTS cantidad_total_planificada NUMERIC(15, 3) DEFAULT 0;

ALTER TABLE etapas_obra
ADD COLUMN IF NOT EXISTS cantidad_total_ejecutada NUMERIC(15, 3) DEFAULT 0;

ALTER TABLE etapas_obra
ADD COLUMN IF NOT EXISTS porcentaje_avance_medicion INTEGER DEFAULT 0;

-- Comentarios para documentación
COMMENT ON COLUMN etapas_obra.unidad_medida IS 'Unidad de medida: m2, m3, ml, u, hrs';
COMMENT ON COLUMN etapas_obra.cantidad_total_planificada IS 'Cantidad total planificada para la etapa';
COMMENT ON COLUMN etapas_obra.cantidad_total_ejecutada IS 'Cantidad total ejecutada/realizada';
COMMENT ON COLUMN etapas_obra.porcentaje_avance_medicion IS 'Porcentaje de avance calculado por medición (0-100)';

-- Índice para consultas de avance
CREATE INDEX IF NOT EXISTS idx_etapas_obra_avance ON etapas_obra(obra_id, porcentaje_avance_medicion);
