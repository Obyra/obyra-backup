-- Migración: Liquidación de Mano de Obra
-- Fecha: 2026-03-12

CREATE TABLE IF NOT EXISTS liquidaciones_mo (
    id SERIAL PRIMARY KEY,
    obra_id INTEGER NOT NULL REFERENCES obras(id),
    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
    periodo_desde DATE NOT NULL,
    periodo_hasta DATE NOT NULL,
    estado VARCHAR(20) DEFAULT 'pendiente',
    notas TEXT,
    monto_total NUMERIC(15,2) DEFAULT 0,
    created_by_id INTEGER REFERENCES usuarios(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_liq_mo_obra ON liquidaciones_mo(obra_id);
CREATE INDEX IF NOT EXISTS ix_liq_mo_estado ON liquidaciones_mo(estado);

CREATE TABLE IF NOT EXISTS liquidaciones_mo_items (
    id SERIAL PRIMARY KEY,
    liquidacion_id INTEGER NOT NULL REFERENCES liquidaciones_mo(id) ON DELETE CASCADE,
    operario_id INTEGER NOT NULL REFERENCES usuarios(id),
    horas_avance NUMERIC(8,2) DEFAULT 0,
    horas_fichadas NUMERIC(8,2) DEFAULT 0,
    horas_liquidadas NUMERIC(8,2) DEFAULT 0,
    tarifa_hora NUMERIC(12,2) DEFAULT 0,
    monto NUMERIC(15,2) DEFAULT 0,
    estado VARCHAR(20) DEFAULT 'pendiente',
    metodo_pago VARCHAR(30),
    fecha_pago DATE,
    comprobante_url VARCHAR(500),
    pagado_por_id INTEGER REFERENCES usuarios(id),
    pagado_at TIMESTAMP,
    notas TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_liq_mo_item_liq ON liquidaciones_mo_items(liquidacion_id);
CREATE INDEX IF NOT EXISTS ix_liq_mo_item_op ON liquidaciones_mo_items(operario_id);
CREATE INDEX IF NOT EXISTS ix_liq_mo_item_estado ON liquidaciones_mo_items(estado);
