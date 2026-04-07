"""
Runtime database migrations extracted from app.py for maintainability.
All migrations use idempotent DO $$ blocks — safe to re-run on every startup.
"""
import os

from sqlalchemy import text


def run_runtime_migrations(db, app):
    """Execute all runtime schema migrations inside an app context."""
    from models import Usuario, Organizacion

    # ============================================================================
    # PHASE 4 REFACTORING (Nov 2025):
    # Runtime migrations have been converted to Alembic migrations.
    # All schema changes are now in migrations/versions/*.py
    #
    # To apply pending migrations:
    #   docker-compose exec app alembic upgrade head
    #
    # Legacy file: migrations_runtime.py → _migrations_runtime_old.py
    # ============================================================================

    # En Railway/producción: crear todas las tablas si no existen
    # Esto es necesario porque las migraciones de Alembic usan schema "app"
    # que no existe en Railway (usa "public" por defecto)
    _is_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None or \
                  os.getenv("RAILWAY_PROJECT_ID") is not None
    if _is_railway:
        try:
            db.create_all()
            print("[OK] Railway: All database tables created/verified")
        except Exception as e:
            print(f"[WARN] Railway db.create_all() error: {e}")

    # Backfill: sincronizar plan_activo de usuarios con plan_tipo de su org
    # Soluciona inconsistencia donde super admin activó planes manualmente
    # actualizando solo organizacion.plan_tipo y dejando usuarios con plan_activo='prueba'
    try:
        sync_plan_sql = """
        UPDATE usuarios u
        SET plan_activo = o.plan_tipo,
            fecha_expiracion_plan = o.fecha_fin_plan
        FROM organizaciones o
        WHERE u.organizacion_id = o.id
          AND o.plan_tipo IS NOT NULL
          AND o.plan_tipo != 'prueba'
          AND (u.plan_activo IS NULL OR u.plan_activo != o.plan_tipo);
        """
        result = db.session.execute(text(sync_plan_sql))
        db.session.commit()
        if result.rowcount:
            print(f"[OK] Sincronizado plan_activo en {result.rowcount} usuarios")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Sync plan_activo skipped: {e}")

    # Migración automática: branding (nombre_fantasia, color_primario)
    try:
        branding_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='nombre_fantasia') THEN
                ALTER TABLE organizaciones ADD COLUMN nombre_fantasia VARCHAR(200);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='color_primario') THEN
                ALTER TABLE organizaciones ADD COLUMN color_primario VARCHAR(7);
            END IF;
        END $$;
        """
        db.session.execute(text(branding_sql))
        db.session.commit()
        print("[OK] Branding columns ensured (nombre_fantasia, color_primario)")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Branding migration error: {e}")

    # Migración automática: agregar columnas de planes a organizaciones
    try:
        plan_columns_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='plan_tipo') THEN
                ALTER TABLE organizaciones ADD COLUMN plan_tipo VARCHAR(50) DEFAULT 'prueba';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='max_usuarios') THEN
                ALTER TABLE organizaciones ADD COLUMN max_usuarios INTEGER DEFAULT 5;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='fecha_inicio_plan') THEN
                ALTER TABLE organizaciones ADD COLUMN fecha_inicio_plan TIMESTAMP;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='fecha_fin_plan') THEN
                ALTER TABLE organizaciones ADD COLUMN fecha_fin_plan TIMESTAMP;
            END IF;
        END $$;
        """
        db.session.execute(text(plan_columns_sql))
        db.session.commit()
        print("[OK] Plan columns migration applied")
    except Exception as e:
        print(f"[WARN] Plan columns migration skipped: {e}")

    # Migración automática: columnas faltantes en Railway
    try:
        missing_cols_sql = """
        DO $$
        BEGIN
            -- logo_url en organizaciones
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='logo_url') THEN
                ALTER TABLE organizaciones ADD COLUMN logo_url VARCHAR(500);
            END IF;
            -- logo_url en proveedores
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='proveedores' AND column_name='logo_url') THEN
                ALTER TABLE proveedores ADD COLUMN logo_url VARCHAR(500);
            END IF;
            -- confirmado_como_obra en presupuestos
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='presupuestos' AND column_name='confirmado_como_obra') THEN
                ALTER TABLE presupuestos ADD COLUMN confirmado_como_obra BOOLEAN DEFAULT false;
            END IF;
        END $$;
        """
        db.session.execute(text(missing_cols_sql))
        db.session.commit()
        print("[OK] Missing columns migration applied (logo_url, confirmado_como_obra)")
    except Exception as e:
        print(f"[WARN] Missing columns migration skipped: {e}")

    # Migración: tabla niveles_presupuesto y columna nivel_nombre
    try:
        niveles_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='niveles_presupuesto') THEN
                CREATE TABLE niveles_presupuesto (
                    id SERIAL PRIMARY KEY,
                    presupuesto_id INTEGER NOT NULL REFERENCES presupuestos(id),
                    tipo_nivel VARCHAR(30) NOT NULL,
                    nombre VARCHAR(100) NOT NULL,
                    orden INTEGER NOT NULL DEFAULT 0,
                    repeticiones INTEGER NOT NULL DEFAULT 1,
                    area_m2 NUMERIC(10,2) NOT NULL,
                    sistema_constructivo VARCHAR(30) NOT NULL DEFAULT 'hormigon',
                    atributos JSONB DEFAULT '{}'::jsonb
                );
                CREATE INDEX ix_niveles_pres_id ON niveles_presupuesto(presupuesto_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='items_presupuesto' AND column_name='nivel_nombre') THEN
                ALTER TABLE items_presupuesto ADD COLUMN nivel_nombre VARCHAR(100);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='niveles_presupuesto' AND column_name='hormigon_m3') THEN
                ALTER TABLE niveles_presupuesto ADD COLUMN hormigon_m3 NUMERIC(10,2) DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='niveles_presupuesto' AND column_name='albanileria_m2') THEN
                ALTER TABLE niveles_presupuesto ADD COLUMN albanileria_m2 NUMERIC(10,2) DEFAULT 0;
            END IF;
        END $$;
        """
        db.session.execute(text(niveles_sql))
        db.session.commit()
        print("[OK] Niveles presupuesto migration applied")
    except Exception as e:
        print(f"[WARN] Niveles presupuesto migration skipped: {e}")

    # Fichadas table + radio_fichada_metros column
    try:
        fichadas_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_schema='public' AND table_name='fichadas') THEN
                CREATE TABLE fichadas (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    tipo VARCHAR(10) NOT NULL,
                    fecha_hora TIMESTAMP NOT NULL DEFAULT NOW(),
                    latitud NUMERIC(10,8),
                    longitud NUMERIC(11,8),
                    precision_gps NUMERIC(8,2),
                    distancia_obra NUMERIC(8,2),
                    dentro_rango BOOLEAN DEFAULT FALSE,
                    ip_address VARCHAR(45),
                    user_agent VARCHAR(300),
                    nota TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX idx_fichadas_usuario ON fichadas(usuario_id);
                CREATE INDEX idx_fichadas_obra ON fichadas(obra_id);
                CREATE INDEX idx_fichadas_fecha ON fichadas(fecha_hora);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='obras' AND column_name='radio_fichada_metros') THEN
                ALTER TABLE obras ADD COLUMN radio_fichada_metros INTEGER DEFAULT 200;
            END IF;
        END $$;
        """
        db.session.execute(text(fichadas_sql))
        db.session.commit()
        print("[OK] Fichadas migration applied")
    except Exception as e:
        print(f"[WARN] Fichadas migration skipped: {e}")

    # Migración: campos de precio de compra en requerimiento_compra_items
    try:
        compra_items_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='precio_unitario_compra') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN precio_unitario_compra NUMERIC(15,2);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='cantidad_comprada') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN cantidad_comprada NUMERIC(10,3);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='proveedor_compra') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN proveedor_compra VARCHAR(200);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='factura_compra') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN factura_compra VARCHAR(100);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='fecha_compra') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN fecha_compra DATE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='fecha_pedido') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN fecha_pedido DATE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='requerimiento_compra_items' AND column_name='fecha_entrega_aprox') THEN
                ALTER TABLE requerimiento_compra_items ADD COLUMN fecha_entrega_aprox DATE;
            END IF;
        END $$;
        """
        db.session.execute(text(compra_items_sql))
        db.session.commit()
        print("[OK] Requerimiento compra items price fields migration applied")
    except Exception as e:
        print(f"[WARN] Requerimiento compra items migration skipped: {e}")

    # Ordenes de Compra + Recepciones + CAJA tables
    try:
        oc_sql = """
        DO $$
        BEGIN
            -- Ordenes de compra
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='ordenes_compra') THEN
                CREATE TABLE ordenes_compra (
                    id SERIAL PRIMARY KEY,
                    numero VARCHAR(20) UNIQUE NOT NULL,
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    requerimiento_id INTEGER REFERENCES requerimientos_compra(id),
                    proveedor VARCHAR(200) NOT NULL,
                    proveedor_cuit VARCHAR(20),
                    proveedor_contacto VARCHAR(200),
                    estado VARCHAR(20) DEFAULT 'borrador',
                    moneda VARCHAR(3) DEFAULT 'ARS',
                    subtotal NUMERIC(15,2) DEFAULT 0,
                    iva NUMERIC(15,2) DEFAULT 0,
                    total NUMERIC(15,2) DEFAULT 0,
                    fecha_emision DATE,
                    fecha_entrega_estimada DATE,
                    fecha_entrega_real DATE,
                    condicion_pago VARCHAR(100),
                    notas TEXT,
                    created_by_id INTEGER REFERENCES usuarios(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_oc_org ON ordenes_compra(organizacion_id);
                CREATE INDEX ix_oc_obra ON ordenes_compra(obra_id);
                CREATE INDEX ix_oc_estado ON ordenes_compra(estado);
            END IF;

            -- Items de OC
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='orden_compra_items') THEN
                CREATE TABLE orden_compra_items (
                    id SERIAL PRIMARY KEY,
                    orden_compra_id INTEGER NOT NULL REFERENCES ordenes_compra(id) ON DELETE CASCADE,
                    item_inventario_id INTEGER REFERENCES items_inventario(id),
                    descripcion VARCHAR(300) NOT NULL,
                    cantidad NUMERIC(10,3) NOT NULL,
                    unidad VARCHAR(30) DEFAULT 'unidad',
                    precio_unitario NUMERIC(15,2) DEFAULT 0,
                    subtotal NUMERIC(15,2) DEFAULT 0,
                    cantidad_recibida NUMERIC(10,3) DEFAULT 0
                );
                CREATE INDEX ix_oci_oc ON orden_compra_items(orden_compra_id);
            END IF;

            -- Recepciones de OC
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='recepciones_oc') THEN
                CREATE TABLE recepciones_oc (
                    id SERIAL PRIMARY KEY,
                    orden_compra_id INTEGER NOT NULL REFERENCES ordenes_compra(id) ON DELETE CASCADE,
                    fecha_recepcion DATE NOT NULL,
                    recibido_por_id INTEGER NOT NULL REFERENCES usuarios(id),
                    remito_numero VARCHAR(100),
                    notas TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_rec_oc ON recepciones_oc(orden_compra_id);
            END IF;

            -- Items de recepcion
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='recepcion_oc_items') THEN
                CREATE TABLE recepcion_oc_items (
                    id SERIAL PRIMARY KEY,
                    recepcion_id INTEGER NOT NULL REFERENCES recepciones_oc(id) ON DELETE CASCADE,
                    oc_item_id INTEGER NOT NULL REFERENCES orden_compra_items(id),
                    cantidad_recibida NUMERIC(10,3) NOT NULL
                );
                CREATE INDEX ix_reci_rec ON recepcion_oc_items(recepcion_id);
            END IF;

            -- Movimientos de Caja
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='movimientos_caja') THEN
                CREATE TABLE movimientos_caja (
                    id SERIAL PRIMARY KEY,
                    numero VARCHAR(20) UNIQUE NOT NULL,
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    tipo VARCHAR(20) NOT NULL,
                    monto NUMERIC(15,2) NOT NULL,
                    moneda VARCHAR(3) DEFAULT 'ARS',
                    concepto VARCHAR(300),
                    referencia VARCHAR(100),
                    orden_compra_id INTEGER REFERENCES ordenes_compra(id),
                    fecha_movimiento DATE NOT NULL,
                    estado VARCHAR(20) DEFAULT 'pendiente',
                    comprobante_url VARCHAR(500),
                    created_by_id INTEGER REFERENCES usuarios(id),
                    confirmado_por_id INTEGER REFERENCES usuarios(id),
                    fecha_confirmacion TIMESTAMP,
                    notas TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_mc_org ON movimientos_caja(organizacion_id);
                CREATE INDEX ix_mc_obra ON movimientos_caja(obra_id);
                CREATE INDEX ix_mc_estado ON movimientos_caja(estado);
            END IF;

            -- Tipos de documento (para Legajo Digital)
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='tipos_documento') THEN
                CREATE TABLE tipos_documento (
                    id SERIAL PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL,
                    categoria VARCHAR(50) NOT NULL,
                    requiere_aprobacion BOOLEAN DEFAULT FALSE,
                    retencion_anos INTEGER DEFAULT 10,
                    activo BOOLEAN DEFAULT TRUE
                );
                INSERT INTO tipos_documento (nombre, categoria) VALUES
                    ('Contrato', 'contractual'),
                    ('Planos', 'tecnico'),
                    ('Renders', 'tecnico'),
                    ('Pliego de Especificaciones', 'tecnico'),
                    ('Memoria de Calculo', 'tecnico'),
                    ('Presupuesto', 'administrativo'),
                    ('Otros', 'general');
            END IF;

            -- Documentos de obra
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='documentos_obra') THEN
                CREATE TABLE documentos_obra (
                    id SERIAL PRIMARY KEY,
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    tipo_documento_id INTEGER NOT NULL REFERENCES tipos_documento(id),
                    organizacion_id INTEGER REFERENCES organizaciones(id),
                    nombre VARCHAR(200) NOT NULL,
                    descripcion TEXT,
                    archivo_path VARCHAR(500) NOT NULL,
                    version VARCHAR(10) DEFAULT '1.0',
                    estado VARCHAR(20) DEFAULT 'activo',
                    fecha_creacion TIMESTAMP DEFAULT NOW(),
                    fecha_modificacion TIMESTAMP DEFAULT NOW(),
                    creado_por_id INTEGER NOT NULL REFERENCES usuarios(id),
                    tags VARCHAR(500)
                );
                CREATE INDEX ix_do_obra ON documentos_obra(obra_id);
                CREATE INDEX ix_do_tipo ON documentos_obra(tipo_documento_id);
            END IF;
        END $$;
        """
        db.session.execute(text(oc_sql))
        db.session.commit()
        print("[OK] OC + Caja + Documentos tables migration applied")
    except Exception as e:
        print(f"[WARN] OC + Caja + Documentos migration skipped: {e}")

    # Proveedores OC + Historial precios
    try:
        prov_sql = """
        DO $$ BEGIN
            -- Proveedores OC
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='proveedores_oc') THEN
                CREATE TABLE proveedores_oc (
                    id SERIAL PRIMARY KEY,
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    razon_social VARCHAR(200) NOT NULL,
                    nombre_fantasia VARCHAR(200),
                    cuit VARCHAR(20),
                    tipo VARCHAR(50) DEFAULT 'materiales',
                    email VARCHAR(200),
                    telefono VARCHAR(50),
                    direccion VARCHAR(300),
                    ciudad VARCHAR(100),
                    provincia VARCHAR(100),
                    contacto_nombre VARCHAR(200),
                    contacto_telefono VARCHAR(50),
                    condicion_pago VARCHAR(100),
                    notas TEXT,
                    activo BOOLEAN DEFAULT TRUE,
                    created_by_id INTEGER REFERENCES usuarios(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_prov_oc_org ON proveedores_oc(organizacion_id);
                CREATE INDEX ix_prov_oc_activo ON proveedores_oc(activo);
            END IF;

            -- Historial de precios proveedor
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='historial_precios_proveedor') THEN
                CREATE TABLE historial_precios_proveedor (
                    id SERIAL PRIMARY KEY,
                    proveedor_id INTEGER NOT NULL REFERENCES proveedores_oc(id),
                    item_inventario_id INTEGER REFERENCES items_inventario(id),
                    descripcion_item VARCHAR(300) NOT NULL,
                    precio_unitario NUMERIC(15,2) NOT NULL,
                    moneda VARCHAR(3) DEFAULT 'ARS',
                    orden_compra_id INTEGER REFERENCES ordenes_compra(id),
                    fecha DATE NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_hpp_prov ON historial_precios_proveedor(proveedor_id);
                CREATE INDEX ix_hpp_item ON historial_precios_proveedor(item_inventario_id);
            END IF;

            -- Agregar FK proveedor_oc_id a ordenes_compra si no existe
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='ordenes_compra' AND column_name='proveedor_oc_id') THEN
                ALTER TABLE ordenes_compra ADD COLUMN proveedor_oc_id INTEGER REFERENCES proveedores_oc(id);
            END IF;
        END $$;
        """
        db.session.execute(text(prov_sql))
        db.session.commit()
        print("[OK] Proveedores OC tables migration applied")
    except Exception as e:
        print(f"[WARN] Proveedores OC migration skipped: {e}")

    # Cotizaciones de proveedor tables
    try:
        cot_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='cotizaciones_proveedor') THEN
                CREATE TABLE cotizaciones_proveedor (
                    id SERIAL PRIMARY KEY,
                    requerimiento_id INTEGER NOT NULL REFERENCES requerimientos_compra(id),
                    proveedor_oc_id INTEGER NOT NULL REFERENCES proveedores_oc(id),
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    estado VARCHAR(20) DEFAULT 'borrador',
                    moneda VARCHAR(3) DEFAULT 'ARS',
                    condicion_pago VARCHAR(100),
                    plazo_entrega VARCHAR(100),
                    validez VARCHAR(100),
                    notas TEXT,
                    subtotal NUMERIC(15,2) DEFAULT 0,
                    total NUMERIC(15,2) DEFAULT 0,
                    fecha_solicitud TIMESTAMP DEFAULT NOW(),
                    fecha_recepcion TIMESTAMP,
                    created_by_id INTEGER REFERENCES usuarios(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_cot_prov_req ON cotizaciones_proveedor(requerimiento_id);
                CREATE INDEX ix_cot_prov_org ON cotizaciones_proveedor(organizacion_id);
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='cotizacion_proveedor_items') THEN
                CREATE TABLE cotizacion_proveedor_items (
                    id SERIAL PRIMARY KEY,
                    cotizacion_id INTEGER NOT NULL REFERENCES cotizaciones_proveedor(id) ON DELETE CASCADE,
                    requerimiento_item_id INTEGER REFERENCES requerimiento_compra_items(id),
                    precio_unitario NUMERIC(15,2) DEFAULT 0,
                    subtotal NUMERIC(15,2) DEFAULT 0,
                    descripcion VARCHAR(300) NOT NULL,
                    cantidad NUMERIC(10,3) NOT NULL,
                    unidad VARCHAR(30) DEFAULT 'unidad',
                    item_inventario_id INTEGER REFERENCES items_inventario(id),
                    notas TEXT
                );
                CREATE INDEX ix_cot_item_cot ON cotizacion_proveedor_items(cotizacion_id);
                CREATE INDEX ix_cot_item_req ON cotizacion_proveedor_items(requerimiento_item_id);
            END IF;
        END $$;
        """
        db.session.execute(text(cot_sql))
        db.session.commit()
        print("[OK] Cotizaciones proveedor tables migration applied")
    except Exception as e:
        print(f"[WARN] Cotizaciones proveedor migration skipped: {e}")

    # Modalidad compra/alquiler en cotizacion_proveedor_items
    try:
        db.session.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name='cotizacion_proveedor_items' AND column_name='modalidad') THEN
                ALTER TABLE cotizacion_proveedor_items ADD COLUMN modalidad VARCHAR(20) DEFAULT 'compra';
                ALTER TABLE cotizacion_proveedor_items ADD COLUMN dias_alquiler INTEGER;
            END IF;
        END $$;
        """))
        db.session.commit()
        print("[OK] Cotizaciones modalidad compra/alquiler migration applied")
    except Exception as e:
        print(f"[WARN] Cotizaciones modalidad migration skipped: {e}")

    # Remitos + Stock Obra tables
    try:
        remitos_sql = """
        DO $$
        BEGIN
            -- Remitos
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='remitos') THEN
                CREATE TABLE remitos (
                    id SERIAL PRIMARY KEY,
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    requerimiento_id INTEGER REFERENCES requerimientos_compra(id),
                    numero_remito VARCHAR(50) NOT NULL,
                    proveedor VARCHAR(200) NOT NULL,
                    fecha DATE,
                    estado VARCHAR(30) DEFAULT 'recibido',
                    notas TEXT,
                    archivo_url VARCHAR(500),
                    recibido_por_id INTEGER REFERENCES usuarios(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_remito_obra ON remitos(obra_id);
                CREATE INDEX ix_remito_req ON remitos(requerimiento_id);
            END IF;

            -- Items de remito
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='remito_items') THEN
                CREATE TABLE remito_items (
                    id SERIAL PRIMARY KEY,
                    remito_id INTEGER NOT NULL REFERENCES remitos(id) ON DELETE CASCADE,
                    descripcion VARCHAR(300) NOT NULL,
                    cantidad NUMERIC(10,3) NOT NULL,
                    unidad VARCHAR(20) DEFAULT 'u',
                    observacion VARCHAR(300)
                );
                CREATE INDEX ix_remito_item_remito ON remito_items(remito_id);
            END IF;

            -- Stock en obra
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='stock_obra') THEN
                CREATE TABLE stock_obra (
                    id SERIAL PRIMARY KEY,
                    obra_id INTEGER NOT NULL REFERENCES obras(id),
                    item_inventario_id INTEGER NOT NULL REFERENCES items_inventario(id),
                    cantidad_disponible NUMERIC(12,3) DEFAULT 0,
                    cantidad_consumida NUMERIC(12,3) DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_stock_obra_item UNIQUE (obra_id, item_inventario_id)
                );
                CREATE INDEX ix_stock_obra_obra ON stock_obra(obra_id);
            END IF;

            -- Movimientos de stock en obra
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='movimientos_stock_obra') THEN
                CREATE TABLE movimientos_stock_obra (
                    id SERIAL PRIMARY KEY,
                    stock_obra_id INTEGER NOT NULL REFERENCES stock_obra(id) ON DELETE CASCADE,
                    tipo VARCHAR(20) NOT NULL,
                    cantidad NUMERIC(12,3) NOT NULL,
                    precio_unitario NUMERIC(15,2),
                    motivo VARCHAR(300),
                    usuario_id INTEGER REFERENCES usuarios(id),
                    reserva_id INTEGER,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX ix_mso_stock ON movimientos_stock_obra(stock_obra_id);
            END IF;
        END $$;
        """
        db.session.execute(text(remitos_sql))
        db.session.commit()
        print("[OK] Remitos + Stock Obra tables migration applied")
    except Exception as e:
        print(f"[WARN] Remitos + Stock Obra migration skipped: {e}")

    # Remito <-> OC vinculación
    try:
        remito_oc_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='requerimiento_id') THEN
                ALTER TABLE remitos ADD COLUMN requerimiento_id INTEGER REFERENCES requerimientos_compra(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='proveedor_oc_id') THEN
                ALTER TABLE remitos ADD COLUMN proveedor_oc_id INTEGER REFERENCES proveedores_oc(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='recibido_por_id') THEN
                ALTER TABLE remitos ADD COLUMN recibido_por_id INTEGER REFERENCES usuarios(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='archivo_url') THEN
                ALTER TABLE remitos ADD COLUMN archivo_url VARCHAR(500);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='created_by_id') THEN
                ALTER TABLE remitos ADD COLUMN created_by_id INTEGER REFERENCES usuarios(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='updated_at') THEN
                ALTER TABLE remitos ADD COLUMN updated_at TIMESTAMP;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remitos' AND column_name='orden_compra_id') THEN
                ALTER TABLE remitos ADD COLUMN orden_compra_id INTEGER REFERENCES ordenes_compra(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remito_items' AND column_name='oc_item_id') THEN
                ALTER TABLE remito_items ADD COLUMN oc_item_id INTEGER REFERENCES orden_compra_items(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remito_items' AND column_name='item_inventario_id') THEN
                ALTER TABLE remito_items ADD COLUMN item_inventario_id INTEGER REFERENCES items_inventario(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='remito_items' AND column_name='precio_unitario') THEN
                ALTER TABLE remito_items ADD COLUMN precio_unitario NUMERIC(15,2);
            END IF;
        END $$;
        """
        db.session.execute(text(remito_oc_sql))
        db.session.commit()
        print("[OK] Remito-OC vinculacion migration applied")
    except Exception as e:
        print(f"[WARN] Remito-OC migration skipped: {e}")

    # Etapa dependencies and chaining
    try:
        dep_sql = """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='etapas_obra' AND column_name='nivel_encadenamiento') THEN
                ALTER TABLE etapas_obra ADD COLUMN nivel_encadenamiento INTEGER;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='etapas_obra' AND column_name='fechas_manuales') THEN
                ALTER TABLE etapas_obra ADD COLUMN fechas_manuales BOOLEAN DEFAULT false;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='etapas_obra' AND column_name='es_opcional') THEN
                ALTER TABLE etapas_obra ADD COLUMN es_opcional BOOLEAN DEFAULT false;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='etapa_dependencias') THEN
                CREATE TABLE etapa_dependencias (
                    id SERIAL PRIMARY KEY,
                    etapa_id INTEGER NOT NULL REFERENCES etapas_obra(id) ON DELETE CASCADE,
                    depende_de_id INTEGER NOT NULL REFERENCES etapas_obra(id) ON DELETE CASCADE,
                    tipo VARCHAR(10) DEFAULT 'FS',
                    lag_dias INTEGER DEFAULT 0,
                    UNIQUE(etapa_id, depende_de_id)
                );
                CREATE INDEX idx_etapa_dep_etapa ON etapa_dependencias(etapa_id);
                CREATE INDEX idx_etapa_dep_depende ON etapa_dependencias(depende_de_id);
            END IF;
        END $$;
        """
        db.session.execute(text(dep_sql))
        db.session.commit()
        print("[OK] Etapa dependencies migration applied")
    except Exception as e:
        print(f"[WARN] Etapa dependencies migration skipped: {e}")

    # max_obras en organizaciones
    try:
        db.session.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='max_obras') THEN
                ALTER TABLE organizaciones ADD COLUMN max_obras INTEGER DEFAULT 1;
            END IF;
        END $$;
        """))
        db.session.commit()
        print("[OK] max_obras migration applied")
    except Exception as e:
        print(f"[WARN] max_obras migration skipped: {e}")

    # Equipment: nuevos campos + tabla equipment_movement
    try:
        equip_sql = """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='costo_hora') THEN
                ALTER TABLE equipment ADD COLUMN costo_hora NUMERIC(12,2) DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='nro_serie') THEN
                ALTER TABLE equipment ADD COLUMN nro_serie VARCHAR(100);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='codigo') THEN
                ALTER TABLE equipment ADD COLUMN codigo VARCHAR(50);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='costo_adquisicion') THEN
                ALTER TABLE equipment ADD COLUMN costo_adquisicion NUMERIC(15,2) DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='vida_util_anios') THEN
                ALTER TABLE equipment ADD COLUMN vida_util_anios INTEGER;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='ubicacion_tipo') THEN
                ALTER TABLE equipment ADD COLUMN ubicacion_tipo VARCHAR(20) DEFAULT 'deposito';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='ubicacion_obra_id') THEN
                ALTER TABLE equipment ADD COLUMN ubicacion_obra_id INTEGER REFERENCES obras(id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='moneda') THEN
                ALTER TABLE equipment ADD COLUMN moneda VARCHAR(3) DEFAULT 'ARS';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='costo_hora_usd') THEN
                ALTER TABLE equipment ADD COLUMN costo_hora_usd NUMERIC(12,2);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='costo_adquisicion_usd') THEN
                ALTER TABLE equipment ADD COLUMN costo_adquisicion_usd NUMERIC(15,2);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='equipment_movement') THEN
                CREATE TABLE equipment_movement (
                    id SERIAL PRIMARY KEY,
                    equipment_id INTEGER NOT NULL REFERENCES equipment(id),
                    company_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    tipo VARCHAR(20) NOT NULL,
                    origen_tipo VARCHAR(20) NOT NULL,
                    origen_obra_id INTEGER REFERENCES obras(id),
                    destino_tipo VARCHAR(20) NOT NULL,
                    destino_obra_id INTEGER REFERENCES obras(id),
                    fecha_movimiento TIMESTAMP NOT NULL DEFAULT NOW(),
                    fecha_llegada TIMESTAMP,
                    estado VARCHAR(20) DEFAULT 'en_transito',
                    despachado_por INTEGER NOT NULL REFERENCES usuarios(id),
                    recibido_por INTEGER REFERENCES usuarios(id),
                    notas TEXT,
                    costo_transporte NUMERIC(12,2) DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX idx_eqmov_equipment ON equipment_movement(equipment_id);
                CREATE INDEX idx_eqmov_company ON equipment_movement(company_id);
                CREATE INDEX idx_eqmov_destino ON equipment_movement(destino_obra_id);
            END IF;
        END $$;
        """
        db.session.execute(text(equip_sql))
        db.session.commit()
        print("[OK] Equipment movement migration applied")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Equipment movement migration skipped: {e}")

    # RBAC tables and seeding
    try:
        from models import RoleModule, UserModule, seed_default_role_permissions

        # Create RBAC tables if they don't exist
        RoleModule.__table__.create(db.engine, checkfirst=True)
        UserModule.__table__.create(db.engine, checkfirst=True)

        # Seed default permissions
        seed_default_role_permissions()
        print("[OK] RBAC permissions seeded successfully")
    except Exception as e:
        print(f"[WARN] RBAC seeding skipped: {e}")

    # Marketplace tables mínimas
    try:
        from marketplace.models import (
            MkProduct, MkProductVariant, MkCart, MkCartItem,
            MkOrder, MkOrderItem, MkPayment, MkPurchaseOrder, MkCommission
        )
        MkProduct.__table__.create(db.engine, checkfirst=True)
        MkProductVariant.__table__.create(db.engine, checkfirst=True)
        MkCart.__table__.create(db.engine, checkfirst=True)
        MkCartItem.__table__.create(db.engine, checkfirst=True)
        MkOrder.__table__.create(db.engine, checkfirst=True)
        MkOrderItem.__table__.create(db.engine, checkfirst=True)
        MkPayment.__table__.create(db.engine, checkfirst=True)
        MkPurchaseOrder.__table__.create(db.engine, checkfirst=True)
        MkCommission.__table__.create(db.engine, checkfirst=True)

        if not MkCommission.query.first():
            commission_rates = [
                MkCommission(category_id=1, exposure='standard', take_rate_pct=10.0),
                MkCommission(category_id=1, exposure='premium', take_rate_pct=12.0),
            ]
            for commission in commission_rates:
                db.session.add(commission)
            demo_product = MkProduct(
                seller_company_id=1,
                name="Cemento Portland 50kg",
                category_id=1,
                description_html="<p>Cemento Portland de alta calidad</p>",
                is_masked_seller=True
            )
            db.session.add(demo_product)
            db.session.flush()
            demo_variant = MkProductVariant(
                product_id=demo_product.id,
                sku="CEM-PORT-50KG",
                price=8999.0,
                currency="ARS",
                stock_qty=100
            )
            db.session.add(demo_variant)
            db.session.commit()
        print("[OK] Marketplace tables created and seeded successfully")
    except Exception as e:
        print(f"[WARN] Marketplace initialization skipped: {e}")

    # Índices de performance para reportes de inventario
    try:
        idx_sql = """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_uso_inventario_item_fecha') THEN
                CREATE INDEX ix_uso_inventario_item_fecha ON uso_inventario(item_id, fecha_uso);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_movimientos_inv_item_fecha') THEN
                CREATE INDEX ix_movimientos_inv_item_fecha ON movimientos_inventario(item_id, fecha);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_items_inventario_org_activo') THEN
                CREATE INDEX ix_items_inventario_org_activo ON items_inventario(organizacion_id, activo);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_fichadas_obra_fecha') THEN
                CREATE INDEX ix_fichadas_obra_fecha ON fichadas(obra_id, fecha_hora);
            END IF;
            -- Indices de escalabilidad (audit 2026-03-31)
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_equipment_company') THEN
                CREATE INDEX ix_equipment_company ON equipment(company_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_obras_org_estado_deleted') THEN
                CREATE INDEX ix_obras_org_estado_deleted ON obras(organizacion_id, estado, deleted_at);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_etapas_obra_id') THEN
                CREATE INDEX ix_etapas_obra_id ON etapas_obra(obra_id, orden);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_tareas_etapa_id') THEN
                CREATE INDEX ix_tareas_etapa_id ON tareas_etapa(etapa_id, orden);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_uso_inv_obra') THEN
                CREATE INDEX ix_uso_inv_obra ON uso_inventario(obra_id);
            END IF;
        END $$;
        """
        db.session.execute(text(idx_sql))
        db.session.commit()
        print("[OK] Performance indexes created")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Performance indexes skipped: {e}")

    print("[OK] Database tables created successfully")

    # Asegurar admin por defecto
    try:
        admin_email = 'admin@obyra.com'
        admin = Usuario.query.filter_by(email=admin_email).first()

        if not admin:
            admin_org = Organizacion(nombre='OBYRA - Administración Central')
            db.session.add(admin_org)
            db.session.flush()

            # Contraseña OBLIGATORIA desde variable de entorno
            admin_password = os.environ.get('ADMIN_DEFAULT_PASSWORD')
            if not admin_password:
                print('[ADMIN] ERROR: Variable ADMIN_DEFAULT_PASSWORD no configurada. No se creará admin por defecto.')
                db.session.rollback()
                admin_password = None  # Skip admin creation

            if admin_password:
                admin = Usuario(
                    nombre='Administrador',
                    apellido='OBYRA',
                    email=admin_email,
                    rol='administrador',
                    role='administrador',
                    is_super_admin=True,
                    auth_provider='manual',
                    activo=True,
                    organizacion_id=admin_org.id,
                    primary_org_id=admin_org.id,
                )
                admin.set_password(admin_password, skip_validation=True)
                db.session.add(admin)
                db.session.commit()
                print(f'[ADMIN] Usuario administrador creado: {admin_email} (password desde variable de entorno)')
        else:
            updated = False
            hashed_markers = ('pbkdf2:', 'scrypt:', 'argon2:', 'bcrypt')
            stored_hash = admin.password_hash or ''
            if not stored_hash or not stored_hash.startswith(hashed_markers):
                original_secret = stored_hash or 'admin123'
                admin.set_password(original_secret, skip_validation=True)
                updated = True
            if admin.auth_provider != 'manual':
                admin.auth_provider = 'manual'
                updated = True
            if not admin.is_super_admin:
                admin.is_super_admin = True
                updated = True
            if not admin.organizacion:
                admin_org = Organizacion(nombre='OBYRA - Administración Central')
                db.session.add(admin_org)
                db.session.flush()
                admin.organizacion_id = admin_org.id
                if not admin.primary_org_id:
                    admin.primary_org_id = admin_org.id
                updated = True
            if updated:
                db.session.commit()
                print('[ADMIN] Credenciales del administrador principal verificadas y aseguradas.')
    except Exception as ensure_admin_exc:
        db.session.rollback()
        print(f"[WARN] No se pudo garantizar el usuario admin@obyra.com: {ensure_admin_exc}")

    # Guard permanente: asegurar que solo admin@obyra.com sea super admin
    try:
        admin_user = Usuario.query.filter_by(email='admin@obyra.com').first()
        if admin_user and not admin_user.is_super_admin:
            admin_user.is_super_admin = True
            db.session.commit()
    except Exception as e:
        db.session.rollback()

    # Migración: campos de descuento en organizaciones
    try:
        db.session.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='descuento_porcentaje') THEN
                ALTER TABLE organizaciones ADD COLUMN descuento_porcentaje INTEGER DEFAULT 0;
                ALTER TABLE organizaciones ADD COLUMN descuento_meses INTEGER DEFAULT 0;
                ALTER TABLE organizaciones ADD COLUMN descuento_inicio TIMESTAMP;
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Error creando campos de descuento: {e}")

    # Migración: campo activo en obras (para soft delete)
    try:
        db.session.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='obras' AND column_name='activo') THEN
                ALTER TABLE obras ADD COLUMN activo BOOLEAN DEFAULT TRUE;
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Error creando campo activo en obras: {e}")

    # Soft-delete: agregar deleted_at a obras
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='obras' AND column_name='deleted_at') THEN
                ALTER TABLE obras ADD COLUMN deleted_at TIMESTAMP;
                CREATE INDEX ix_obras_deleted_at ON obras(deleted_at);
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Error creando campo deleted_at en obras: {e}")

    # Plan service: campos de suscripción/licencia en organizaciones
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='organizaciones' AND column_name='contract_type') THEN
                ALTER TABLE organizaciones ADD COLUMN contract_type VARCHAR(20) DEFAULT 'subscription';
                ALTER TABLE organizaciones ADD COLUMN subscription_status VARCHAR(20) DEFAULT 'active';
                ALTER TABLE organizaciones ADD COLUMN grace_period_until TIMESTAMP;
                ALTER TABLE organizaciones ADD COLUMN annual_service_due_date TIMESTAMP;
                ALTER TABLE organizaciones ADD COLUMN annual_service_status VARCHAR(20) DEFAULT 'active';
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Error creando campos de plan en organizaciones: {e}")

    # Migraciones runtime completadas y removidas (2026-03-25):
    # - Índices organizacion_id: ya creados en producción
    # - Unique constraint (org_id, codigo) en items: ya aplicado
    # - CASCADE DELETE en tarea_miembros/tarea_responsables: ya aplicado
    # - Limpieza de duplicados inventario: completada manualmente
    # - Reclasificación encofrados: completada
