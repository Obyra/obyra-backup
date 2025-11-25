-- ============================================
-- Tabla de Catálogo Global de Materiales
-- ============================================
-- Esta tabla almacena un catálogo estandarizado de materiales
-- compartido entre todas las organizaciones para facilitar:
-- - Códigos únicos y consistentes
-- - Comparación de precios entre proveedores
-- - Análisis de mercado
-- - Evitar duplicados

CREATE TABLE IF NOT EXISTS global_material_catalog (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(50) UNIQUE NOT NULL,
    nombre VARCHAR(200) NOT NULL,
    categoria_nombre VARCHAR(100) NOT NULL,
    descripcion TEXT,
    unidad VARCHAR(20) NOT NULL,

    -- Metadatos para variantes (marca, peso, especificaciones)
    marca VARCHAR(100),
    peso_cantidad NUMERIC(10, 3),
    peso_unidad VARCHAR(20),
    especificaciones JSONB,  -- JSON para almacenar propiedades adicionales

    -- Estadísticas de uso
    veces_usado INTEGER DEFAULT 0,
    precio_promedio_ars NUMERIC(10, 2),
    precio_promedio_usd NUMERIC(10, 2),

    -- Auditoría
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by_org_id INTEGER REFERENCES organizaciones(id),

    -- Índices para búsqueda rápida
    CONSTRAINT chk_codigo_format CHECK (codigo ~ '^[A-Z0-9\-]{6,20}$')
);

-- Índices para mejorar performance
CREATE INDEX IF NOT EXISTS idx_global_catalog_codigo ON global_material_catalog(codigo);
CREATE INDEX IF NOT EXISTS idx_global_catalog_nombre ON global_material_catalog USING gin(to_tsvector('spanish', nombre));
CREATE INDEX IF NOT EXISTS idx_global_catalog_categoria ON global_material_catalog(categoria_nombre);
CREATE INDEX IF NOT EXISTS idx_global_catalog_marca ON global_material_catalog(marca);
CREATE INDEX IF NOT EXISTS idx_global_catalog_especificaciones ON global_material_catalog USING gin(especificaciones);

-- Tabla para trackear qué organizaciones usan cada material
CREATE TABLE IF NOT EXISTS global_material_usage (
    id SERIAL PRIMARY KEY,
    material_id INTEGER REFERENCES global_material_catalog(id) ON DELETE CASCADE,
    organizacion_id INTEGER REFERENCES organizaciones(id) ON DELETE CASCADE,
    item_inventario_id INTEGER REFERENCES items_inventario(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(material_id, organizacion_id, item_inventario_id)
);

-- Función para actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_global_catalog_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger para updated_at
DROP TRIGGER IF EXISTS trg_global_catalog_updated_at ON global_material_catalog;
CREATE TRIGGER trg_global_catalog_updated_at
    BEFORE UPDATE ON global_material_catalog
    FOR EACH ROW
    EXECUTE FUNCTION update_global_catalog_timestamp();

-- Insertar materiales estándar iniciales
INSERT INTO global_material_catalog (codigo, nombre, categoria_nombre, descripcion, unidad, marca, peso_cantidad, peso_unidad, especificaciones) VALUES
-- Cementos
('CEM-PORT-50KG-LN', 'Cemento Portland', 'Cemento', 'Cemento Portland tipo I, bolsa de 50kg', 'bolsa', 'Loma Negra', 50, 'kg', '{"tipo": "tipo I", "uso": "general"}'),
('CEM-PORT-50KG-HC', 'Cemento Portland', 'Cemento', 'Cemento Portland tipo I, bolsa de 50kg', 'bolsa', 'Holcim', 50, 'kg', '{"tipo": "tipo I", "uso": "general"}'),
('CEM-PORT-25KG-LN', 'Cemento Portland', 'Cemento', 'Cemento Portland tipo I, bolsa de 25kg', 'bolsa', 'Loma Negra', 25, 'kg', '{"tipo": "tipo I", "uso": "general"}'),
('CEM-ARS-50KG-LN', 'Cemento ARS', 'Cemento', 'Cemento de albañilería resistente a sulfatos, 50kg', 'bolsa', 'Loma Negra', 50, 'kg', '{"tipo": "ARS", "uso": "albañileria"}'),

-- Ladrillos
('LAD-COM-12X18X33', 'Ladrillo Común', 'Mampostería', 'Ladrillo común de construcción 12x18x33cm', 'unidad', NULL, NULL, NULL, '{"medidas": "12x18x33"}'),
('LAD-HUE-12X18X33', 'Ladrillo Hueco', 'Mampostería', 'Ladrillo hueco 12x18x33cm', 'unidad', NULL, NULL, NULL, '{"medidas": "12x18x33", "tipo": "hueco"}'),
('LAD-HUE-18X18X33', 'Ladrillo Hueco', 'Mampostería', 'Ladrillo hueco 18x18x33cm', 'unidad', NULL, NULL, NULL, '{"medidas": "18x18x33", "tipo": "hueco"}'),

-- Arena y agregados
('ARE-GRU-M3', 'Arena Gruesa', 'Agregados', 'Arena gruesa a granel por m³', 'metro3', NULL, NULL, NULL, '{"tipo": "gruesa", "origen": "rio"}'),
('ARE-FIN-M3', 'Arena Fina', 'Agregados', 'Arena fina a granel por m³', 'metro3', NULL, NULL, NULL, '{"tipo": "fina", "origen": "rio"}'),
('PIE-GRA-M3', 'Piedra Partida', 'Agregados', 'Piedra partida 6-20mm por m³', 'metro3', NULL, NULL, NULL, '{"granulometria": "6-20mm"}'),

-- Hierro
('HIE-ADN-420-6MM', 'Hierro ADN 420', 'Hierro', 'Hierro de construcción ADN 420 diámetro 6mm', 'metro', 'Acindar', NULL, NULL, '{"diametro": "6mm", "tipo": "ADN 420"}'),
('HIE-ADN-420-8MM', 'Hierro ADN 420', 'Hierro', 'Hierro de construcción ADN 420 diámetro 8mm', 'metro', 'Acindar', NULL, NULL, '{"diametro": "8mm", "tipo": "ADN 420"}'),
('HIE-ADN-420-10MM', 'Hierro ADN 420', 'Hierro', 'Hierro de construcción ADN 420 diámetro 10mm', 'metro', 'Acindar', NULL, NULL, '{"diametro": "10mm", "tipo": "ADN 420"}'),
('HIE-ADN-420-12MM', 'Hierro ADN 420', 'Hierro', 'Hierro de construcción ADN 420 diámetro 12mm', 'metro', 'Acindar', NULL, NULL, '{"diametro": "12mm", "tipo": "ADN 420"}'),

-- Pinturas
('PIN-LAT-INT-20L-AL', 'Pintura Látex Interior', 'Pintura', 'Pintura látex interior blanco mate 20L', 'litro', 'Alba', 20, 'L', '{"tipo": "latex", "uso": "interior", "terminacion": "mate"}'),
('PIN-LAT-EXT-20L-AL', 'Pintura Látex Exterior', 'Pintura', 'Pintura látex exterior blanco 20L', 'litro', 'Alba', 20, 'L', '{"tipo": "latex", "uso": "exterior"}'),
('PIN-ESM-SIN-1L', 'Esmalte Sintético', 'Pintura', 'Esmalte sintético brillante 1L', 'litro', NULL, 1, 'L', '{"tipo": "esmalte", "terminacion": "brillante"}')

ON CONFLICT (codigo) DO NOTHING;

-- Comentarios para documentación
COMMENT ON TABLE global_material_catalog IS 'Catálogo global de materiales compartido entre todas las organizaciones para estandarización y comparación de precios';
COMMENT ON COLUMN global_material_catalog.codigo IS 'Código único alfanumérico de 6-15 caracteres, ej: CEM-PORT-50KG-LN';
COMMENT ON COLUMN global_material_catalog.especificaciones IS 'JSON con propiedades específicas del material (diámetro, tipo, uso, etc)';
COMMENT ON COLUMN global_material_catalog.veces_usado IS 'Contador de cuántas organizaciones usan este material';
