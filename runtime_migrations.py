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

    # Crear todas las tablas si no existen (bootstrap desde modelos SQLAlchemy).
    # Se dispara en dos casos:
    #  - Railway/producción: porque las migraciones Alembic usan schema "app"
    #    que no existe en Railway (usa "public" por defecto).
    #  - Dev Docker con CREATE_ALL_ON_STARTUP=1: evita problemas de orden entre
    #    migraciones Alembic al arrancar de cero (algunas migraciones intentan
    #    ALTER sobre tablas que otra migración posterior crea). create_all()
    #    las crea todas desde los modelos Python antes de los ALTER.
    _is_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None or \
                  os.getenv("RAILWAY_PROJECT_ID") is not None
    _force_create_all = os.getenv("CREATE_ALL_ON_STARTUP") == "1"
    if _is_railway or _force_create_all:
        try:
            db.create_all()
            origen = "Railway" if _is_railway else "DEV"
            print(f"[OK] {origen}: All database tables created/verified")
        except Exception as e:
            print(f"[WARN] db.create_all() error: {e}")

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

    # Backfill: bump limites de TODAS las organizaciones a sin-restricciones (999/999)
    # OBYRA migro a un solo plan unificado sin restricciones de obras ni usuarios.
    # Incluye prueba, estandar, premium y full_premium.
    try:
        bump_limits_sql = """
        UPDATE organizaciones
        SET max_obras = 999, max_usuarios = 999
        WHERE (max_obras < 999 OR max_usuarios < 999);
        """
        result = db.session.execute(text(bump_limits_sql))
        db.session.commit()
        if result.rowcount:
            print(f"[OK] Bumped limites a 999/999 en {result.rowcount} organizaciones premium")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Bump limites premium skipped: {e}")

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
            -- editado_manual en tareas_etapa: flag para respetar ediciones
            -- del usuario y no sobrescribirlas con distribuir_datos_etapa_a_tareas.
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='tareas_etapa' AND column_name='editado_manual') THEN
                ALTER TABLE tareas_etapa ADD COLUMN editado_manual BOOLEAN NOT NULL DEFAULT false;
            END IF;
            -- modalidad_costo en equipment: compra | alquiler_hora | alquiler_dia
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='modalidad_costo') THEN
                ALTER TABLE equipment ADD COLUMN modalidad_costo VARCHAR(20) NOT NULL DEFAULT 'compra';
            END IF;
            -- costo_dia en equipment: tarifa diaria para modalidad='alquiler_dia'
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='equipment' AND column_name='costo_dia') THEN
                ALTER TABLE equipment ADD COLUMN costo_dia NUMERIC(12,2) DEFAULT 0;
            END IF;
        END $$;
        """
        db.session.execute(text(missing_cols_sql))
        db.session.commit()
        print("[OK] Missing columns migration applied (logo_url, confirmado_como_obra, editado_manual, equipment modalidad_costo/costo_dia)")
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

            -- Modalidad de costo (compra|alquiler) para líneas de equipos en presupuestos
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='items_presupuesto' AND column_name='modalidad_costo') THEN
                ALTER TABLE items_presupuesto ADD COLUMN modalidad_costo VARCHAR(20) DEFAULT 'compra';
                -- Backfill: items de equipos generados por IA son en realidad alquileres
                -- (la IA siempre cotizó precio diario de alquiler pero los guardaba sin etiquetar)
                UPDATE items_presupuesto
                SET modalidad_costo = 'alquiler'
                WHERE tipo = 'equipo' AND origen = 'ia';
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

    # Modalidad de pago de operarios (medida | hora | fichada) + tarifas individuales
    # y trazabilidad de modalidad/cantidad/unidad en items de liquidación MO.
    try:
        pago_operarios_sql = """
        DO $$ BEGIN
            -- Usuario: modalidad de pago y tarifas individuales
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='usuarios' AND column_name='modalidad_pago') THEN
                ALTER TABLE usuarios ADD COLUMN modalidad_pago VARCHAR(20) DEFAULT 'hora';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='usuarios' AND column_name='tarifa_hora') THEN
                ALTER TABLE usuarios ADD COLUMN tarifa_hora NUMERIC(12,2) DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='usuarios' AND column_name='tarifa_m2') THEN
                ALTER TABLE usuarios ADD COLUMN tarifa_m2 NUMERIC(12,2) DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='usuarios' AND column_name='tarifa_jornal') THEN
                ALTER TABLE usuarios ADD COLUMN tarifa_jornal NUMERIC(12,2) DEFAULT 0;
            END IF;

            -- LiquidacionMOItem: trazabilidad de modalidad usada y base liquidada
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='liquidaciones_mo_items' AND column_name='modalidad_pago') THEN
                ALTER TABLE liquidaciones_mo_items ADD COLUMN modalidad_pago VARCHAR(20);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='liquidaciones_mo_items' AND column_name='desglose_tareas') THEN
                ALTER TABLE liquidaciones_mo_items ADD COLUMN desglose_tareas JSONB;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='liquidaciones_mo_items' AND column_name='cantidad_liquidada') THEN
                ALTER TABLE liquidaciones_mo_items ADD COLUMN cantidad_liquidada NUMERIC(12,3) DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='liquidaciones_mo_items' AND column_name='unidad_liquidada') THEN
                ALTER TABLE liquidaciones_mo_items ADD COLUMN unidad_liquidada VARCHAR(10);
            END IF;
        END $$;
        """
        db.session.execute(text(pago_operarios_sql))
        db.session.commit()
        print("[OK] Modalidad pago operarios + trazabilidad liquidacion migration applied")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Modalidad pago operarios migration skipped: {e}")

    # Ampliar precision de precio_unitario y total en items_presupuesto
    # (algunas licitaciones manejan montos > $99M, que no entran en Numeric(10,2))
    try:
        db.session.execute(text("""
        DO $$ BEGIN
            -- precio_unitario: 10,2 -> 15,2
            IF EXISTS (SELECT 1 FROM information_schema.columns
                      WHERE table_name='items_presupuesto' AND column_name='precio_unitario'
                      AND numeric_precision=10) THEN
                ALTER TABLE items_presupuesto ALTER COLUMN precio_unitario TYPE NUMERIC(15,2);
            END IF;
            -- cantidad: 10,3 -> 15,3
            IF EXISTS (SELECT 1 FROM information_schema.columns
                      WHERE table_name='items_presupuesto' AND column_name='cantidad'
                      AND numeric_precision=10) THEN
                ALTER TABLE items_presupuesto ALTER COLUMN cantidad TYPE NUMERIC(15,3);
            END IF;
        END $$;
        """))
        db.session.commit()
        print("[OK] items_presupuesto precision ampliada (precio_unitario 15,2; cantidad 15,3)")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Ampliacion precision items_presupuesto skipped: {e}")

    # Solicitud de cotizacion a proveedores via WhatsApp (desde Presupuesto)
    try:
        cotizacion_wa_sql = """
        DO $$ BEGIN
            -- Pivot item-presupuesto <-> proveedor
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='item_presupuesto_proveedores') THEN
                CREATE TABLE item_presupuesto_proveedores (
                    id SERIAL PRIMARY KEY,
                    item_presupuesto_id INTEGER NOT NULL REFERENCES items_presupuesto(id) ON DELETE CASCADE,
                    proveedor_oc_id INTEGER NOT NULL REFERENCES proveedores_oc(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_item_prov UNIQUE (item_presupuesto_id, proveedor_oc_id)
                );
                CREATE INDEX idx_ipp_item ON item_presupuesto_proveedores(item_presupuesto_id);
                CREATE INDEX idx_ipp_prov ON item_presupuesto_proveedores(proveedor_oc_id);
            END IF;

            -- Solicitud cotizacion WhatsApp
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='solicitudes_cotizacion_wa') THEN
                CREATE TABLE solicitudes_cotizacion_wa (
                    id SERIAL PRIMARY KEY,
                    numero VARCHAR(20),
                    organizacion_id INTEGER NOT NULL REFERENCES organizaciones(id),
                    presupuesto_id INTEGER NOT NULL REFERENCES presupuestos(id),
                    proveedor_oc_id INTEGER NOT NULL REFERENCES proveedores_oc(id),
                    telefono_destino VARCHAR(20),
                    mensaje_enviado TEXT,
                    canal VARCHAR(20) DEFAULT 'wa_link',
                    estado VARCHAR(20) DEFAULT 'borrador',
                    items_snapshot JSONB,
                    created_by_id INTEGER REFERENCES usuarios(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    fecha_envio TIMESTAMP,
                    fecha_respuesta TIMESTAMP,
                    respuesta_texto TEXT,
                    notas TEXT
                );
                CREATE INDEX idx_scw_org ON solicitudes_cotizacion_wa(organizacion_id);
                CREATE INDEX idx_scw_presu ON solicitudes_cotizacion_wa(presupuesto_id);
                CREATE INDEX idx_scw_prov ON solicitudes_cotizacion_wa(proveedor_oc_id);
                CREATE INDEX idx_scw_numero ON solicitudes_cotizacion_wa(numero);
            END IF;
        END $$;
        """
        db.session.execute(text(cotizacion_wa_sql))
        db.session.commit()
        print("[OK] Cotizacion WhatsApp tables migration applied")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Cotizacion WhatsApp migration skipped: {e}")

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

    # Sincronizar stock_actual de items_inventario con stock_obra
    # (stock_obra se actualiza por OC/Remito pero items_inventario.stock_actual no se sincronizaba)
    try:
        sync_stock_sql = """
        UPDATE items_inventario ii
        SET stock_actual = sub.total_disponible
        FROM (
            SELECT item_inventario_id, SUM(cantidad_disponible) as total_disponible
            FROM stock_obra
            GROUP BY item_inventario_id
        ) sub
        WHERE ii.id = sub.item_inventario_id
          AND (ii.stock_actual IS NULL OR ii.stock_actual != sub.total_disponible);
        """
        result = db.session.execute(text(sync_stock_sql))
        db.session.commit()
        if result.rowcount:
            print(f"[OK] Sincronizado stock_actual en {result.rowcount} items de inventario")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Sync stock_actual skipped: {e}")

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

    # Migración: agregar organizacion_id a tablas de seguridad que no la tienen
    seguridad_tables = [
        'protocolos_seguridad',
        'checklists_seguridad',
        'incidentes_seguridad',
        'certificaciones_personal',
        'auditorias_seguridad',
    ]
    for tabla in seguridad_tables:
        try:
            db.session.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                              WHERE table_name='{tabla}' AND column_name='organizacion_id') THEN
                    ALTER TABLE {tabla} ADD COLUMN organizacion_id INTEGER REFERENCES organizaciones(id);
                    CREATE INDEX IF NOT EXISTS idx_{tabla}_org_id ON {tabla}(organizacion_id);
                END IF;
            END $$;
            """))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"[WARN] Migración seguridad {tabla}: {e}")

    # Presupuesto Ejecutivo: MaterialCotizable (consolidación de materiales para cotizar a proveedores)
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='materiales_cotizables') THEN
                CREATE TABLE materiales_cotizables (
                    id SERIAL PRIMARY KEY,
                    presupuesto_id INTEGER NOT NULL REFERENCES presupuestos(id) ON DELETE CASCADE,
                    descripcion VARCHAR(300) NOT NULL,
                    unidad VARCHAR(20) NOT NULL,
                    cantidad_total NUMERIC(15, 3) NOT NULL DEFAULT 0,
                    item_inventario_id INTEGER REFERENCES items_inventario(id),
                    grupo_hash VARCHAR(64) NOT NULL,
                    estado VARCHAR(20) NOT NULL DEFAULT 'nuevo',
                    proveedor_elegido_id INTEGER REFERENCES proveedores_oc(id),
                    precio_elegido NUMERIC(15, 2),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_material_cotizable_pres_hash UNIQUE (presupuesto_id, grupo_hash)
                );
                CREATE INDEX ix_materiales_cotizables_presupuesto ON materiales_cotizables(presupuesto_id);
            END IF;
            -- FK desde items_presupuesto_composicion hacia materiales_cotizables
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='items_presupuesto_composicion' AND column_name='material_cotizable_id') THEN
                ALTER TABLE items_presupuesto_composicion
                    ADD COLUMN material_cotizable_id INTEGER
                    REFERENCES materiales_cotizables(id) ON DELETE SET NULL;
                CREATE INDEX ix_ipc_material_cotizable ON items_presupuesto_composicion(material_cotizable_id);
            END IF;
            -- Columna tipo en materiales_cotizables (distinguir material vs equipo)
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='materiales_cotizables' AND column_name='tipo') THEN
                ALTER TABLE materiales_cotizables
                    ADD COLUMN tipo VARCHAR(20) NOT NULL DEFAULT 'material';
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Migracion materiales_cotizables: {e}")

    # Presupuesto Ejecutivo - Fase B: cotización de materiales a proveedores
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            -- SolicitudCotizacionMaterial (1 por proveedor, con N items)
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='solicitudes_cotizacion_material') THEN
                CREATE TABLE solicitudes_cotizacion_material (
                    id SERIAL PRIMARY KEY,
                    presupuesto_id INTEGER NOT NULL REFERENCES presupuestos(id) ON DELETE CASCADE,
                    proveedor_id INTEGER NOT NULL REFERENCES proveedores_oc(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL DEFAULT 1,
                    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fecha_enviado TIMESTAMP,
                    fecha_respondido TIMESTAMP,
                    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                    mensaje_texto TEXT,
                    wa_url TEXT,
                    notas TEXT
                );
                CREATE INDEX ix_solicitudes_cot_mat_presupuesto ON solicitudes_cotizacion_material(presupuesto_id);
                CREATE INDEX ix_solicitudes_cot_mat_proveedor ON solicitudes_cotizacion_material(proveedor_id);
            END IF;
            -- Items de la solicitud (recurso cotizado)
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='solicitud_cotizacion_material_items') THEN
                CREATE TABLE solicitud_cotizacion_material_items (
                    id SERIAL PRIMARY KEY,
                    solicitud_id INTEGER NOT NULL REFERENCES solicitudes_cotizacion_material(id) ON DELETE CASCADE,
                    material_cotizable_id INTEGER NOT NULL REFERENCES materiales_cotizables(id) ON DELETE CASCADE,
                    descripcion_snapshot VARCHAR(300) NOT NULL,
                    unidad_snapshot VARCHAR(20) NOT NULL,
                    cantidad_snapshot NUMERIC(15, 3) NOT NULL DEFAULT 0,
                    precio_respuesta NUMERIC(15, 2),
                    notas_respuesta TEXT,
                    elegido BOOLEAN NOT NULL DEFAULT false
                );
                CREATE INDEX ix_solicitud_cot_mat_items_solicitud ON solicitud_cotizacion_material_items(solicitud_id);
                CREATE INDEX ix_solicitud_cot_mat_items_material ON solicitud_cotizacion_material_items(material_cotizable_id);
            END IF;
            -- Asignaciones (intención antes de enviar)
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='proveedores_asignados_material') THEN
                CREATE TABLE proveedores_asignados_material (
                    id SERIAL PRIMARY KEY,
                    material_cotizable_id INTEGER NOT NULL REFERENCES materiales_cotizables(id) ON DELETE CASCADE,
                    proveedor_id INTEGER NOT NULL REFERENCES proveedores_oc(id) ON DELETE CASCADE,
                    solicitud_item_id INTEGER REFERENCES solicitud_cotizacion_material_items(id) ON DELETE SET NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_asignacion_material_proveedor UNIQUE (material_cotizable_id, proveedor_id)
                );
                CREATE INDEX ix_proveedores_asignados_material ON proveedores_asignados_material(material_cotizable_id);
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Migracion Fase B cotizacion materiales: {e}")

    # Presupuesto Ejecutivo: flag solo_interno en items_presupuesto para etapas internas del APU
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='items_presupuesto' AND column_name='solo_interno') THEN
                ALTER TABLE items_presupuesto ADD COLUMN solo_interno BOOLEAN NOT NULL DEFAULT false;
                CREATE INDEX ix_items_presupuesto_solo_interno ON items_presupuesto(presupuesto_id, solo_interno);
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Migracion solo_interno: {e}")

    # Presupuesto Ejecutivo: flag ejecutivo_aprobado en presupuestos
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='presupuestos' AND column_name='ejecutivo_aprobado') THEN
                ALTER TABLE presupuestos ADD COLUMN ejecutivo_aprobado BOOLEAN NOT NULL DEFAULT false;
                ALTER TABLE presupuestos ADD COLUMN ejecutivo_aprobado_at TIMESTAMP;
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Migracion ejecutivo_aprobado: {e}")

    # Presupuesto Ejecutivo (APU): composicion de items del pliego
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='items_presupuesto_composicion') THEN
                CREATE TABLE items_presupuesto_composicion (
                    id SERIAL PRIMARY KEY,
                    item_presupuesto_id INTEGER NOT NULL REFERENCES items_presupuesto(id) ON DELETE CASCADE,
                    tipo VARCHAR(20) NOT NULL,
                    descripcion VARCHAR(300) NOT NULL,
                    unidad VARCHAR(20) NOT NULL,
                    cantidad NUMERIC(15, 3) NOT NULL DEFAULT 0,
                    precio_unitario NUMERIC(15, 2) NOT NULL DEFAULT 0,
                    total NUMERIC(15, 2) NOT NULL DEFAULT 0,
                    item_inventario_id INTEGER REFERENCES items_inventario(id),
                    modalidad_costo VARCHAR(20),
                    notas TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX ix_ipc_item_presupuesto ON items_presupuesto_composicion(item_presupuesto_id);
            END IF;
            -- Agregar modalidad_costo si la tabla ya existia pre-fase
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='items_presupuesto_composicion' AND column_name='modalidad_costo') THEN
                ALTER TABLE items_presupuesto_composicion ADD COLUMN modalidad_costo VARCHAR(20);
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Migracion items_presupuesto_composicion: {e}")

    # Presupuesto - Gap 18: guardar Excel pliego como documento contractual
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='presupuestos' AND column_name='archivo_pliego_path') THEN
                ALTER TABLE presupuestos ADD COLUMN archivo_pliego_path VARCHAR(500);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='presupuestos' AND column_name='archivo_pliego_nombre') THEN
                ALTER TABLE presupuestos ADD COLUMN archivo_pliego_nombre VARCHAR(255);
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Migracion archivo_pliego: {e}")

    # Presupuesto Ejecutivo - Gap 14+15: vinculo etapa interna -> rubro pliego
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_name='etapa_interna_vinculos') THEN
                CREATE TABLE etapa_interna_vinculos (
                    id SERIAL PRIMARY KEY,
                    presupuesto_id INTEGER NOT NULL REFERENCES presupuestos(id) ON DELETE CASCADE,
                    etapa_interna_nombre VARCHAR(200) NOT NULL,
                    etapa_pliego_nombre VARCHAR(200) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_etapa_interna_vinculo UNIQUE (presupuesto_id, etapa_interna_nombre)
                );
                CREATE INDEX ix_etapa_interna_vinculos_presupuesto ON etapa_interna_vinculos(presupuesto_id);
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Migracion etapa_interna_vinculos: {e}")

    # Migraciones runtime completadas y removidas (2026-03-25):
    # - Índices organizacion_id: ya creados en producción
    # - Unique constraint (org_id, codigo) en items: ya aplicado
    # - CASCADE DELETE en tarea_miembros/tarea_responsables: ya aplicado
    # - Limpieza de duplicados inventario: completada manualmente
    # - Reclasificación encofrados: completada

    # =====================================================
    # 2026-04-29: Directorio global de proveedores
    # Espejo de migrations/versions/20260429_directorio_proveedores_globales.py
    # En Railway las migraciones Alembic con schema 'app' no corren bien,
    # asi que replicamos los ALTER aca (idempotentes con IF NOT EXISTS).
    # `db.create_all()` ya crea las tablas zonas y contactos_proveedor por modelos.
    # =====================================================
    try:
        # 1) organizacion_id nullable (NULL = proveedor global)
        db.session.execute(db.text(
            "ALTER TABLE proveedores_oc ALTER COLUMN organizacion_id DROP NOT NULL;"
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] proveedores_oc.organizacion_id nullable: {e}")

    # 2) Columnas nuevas del directorio
    columnas_proveedores = [
        ("scope", "VARCHAR(20) NOT NULL DEFAULT 'tenant'"),
        ("external_key", "VARCHAR(160)"),
        ("categoria", "VARCHAR(120)"),
        ("subcategoria", "VARCHAR(160)"),
        ("tier", "VARCHAR(20)"),
        ("zona_id", "INTEGER"),
        ("ubicacion_detalle", "VARCHAR(255)"),
        ("cobertura", "VARCHAR(255)"),
        ("web", "VARCHAR(300)"),
        ("tipo_alianza", "VARCHAR(80)"),
    ]
    for col, ddl in columnas_proveedores:
        try:
            db.session.execute(db.text(
                f"ALTER TABLE proveedores_oc ADD COLUMN IF NOT EXISTS {col} {ddl};"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"[WARN] proveedores_oc.{col}: {e}")

    # 3) FK zona_id -> zonas(id) (solo si la tabla zonas existe)
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='zonas')
               AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_proveedores_oc_zona') THEN
                ALTER TABLE proveedores_oc
                    ADD CONSTRAINT fk_proveedores_oc_zona
                    FOREIGN KEY (zona_id) REFERENCES zonas(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] FK proveedores_oc.zona_id: {e}")

    # 4) CHECK constraint scope IN ('tenant','global')
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ck_proveedores_oc_scope') THEN
                ALTER TABLE proveedores_oc
                    ADD CONSTRAINT ck_proveedores_oc_scope
                    CHECK (scope IN ('tenant', 'global'));
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] check scope: {e}")

    # 5) UNIQUE parcial sobre external_key cuando scope='global'
    try:
        db.session.execute(db.text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_proveedores_oc_external_key_global
                ON proveedores_oc(external_key)
                WHERE scope = 'global' AND external_key IS NOT NULL;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] unique external_key: {e}")

    # 6) Indices auxiliares para filtros
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS ix_proveedores_oc_scope ON proveedores_oc(scope);",
        "CREATE INDEX IF NOT EXISTS ix_proveedores_oc_zona_id ON proveedores_oc(zona_id);",
        "CREATE INDEX IF NOT EXISTS ix_proveedores_oc_categoria ON proveedores_oc(categoria);",
        "CREATE INDEX IF NOT EXISTS ix_proveedores_oc_tier ON proveedores_oc(tier);",
    ]:
        try:
            db.session.execute(db.text(idx_sql))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"[WARN] indice proveedores_oc: {e}")

    print("[OK] Migracion runtime: directorio global de proveedores (scope/zona/categoria)")

    # =====================================================
    # 2026-04-29: Tabla categorias_jornal + columnas MO en items_presupuesto
    # Fuente: jornales UOCRA / Camarco. Hibrido: NULL org = global.
    # `db.create_all()` en Railway crea la tabla; aca aseguramos las columnas
    # nuevas en items_presupuesto (que ya existia antes).
    # =====================================================
    columnas_items = [
        ("personas", "INTEGER"),
        ("dias", "NUMERIC(10, 2)"),
        ("categoria_jornal_id", "INTEGER"),
        ("etapa_pliego_vinculada", "VARCHAR(200)"),
    ]
    for col, ddl in columnas_items:
        try:
            db.session.execute(db.text(
                f"ALTER TABLE items_presupuesto ADD COLUMN IF NOT EXISTS {col} {ddl};"
            ))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"[WARN] items_presupuesto.{col}: {e}")

    # FK categoria_jornal_id -> categorias_jornal(id) (solo si la tabla existe)
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='categorias_jornal')
               AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_items_presupuesto_categoria_jornal') THEN
                ALTER TABLE items_presupuesto
                    ADD CONSTRAINT fk_items_presupuesto_categoria_jornal
                    FOREIGN KEY (categoria_jornal_id) REFERENCES categorias_jornal(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] FK items_presupuesto.categoria_jornal_id: {e}")

    # Indices auxiliares
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS ix_items_presupuesto_etapa_vinculada ON items_presupuesto(etapa_pliego_vinculada);",
        "CREATE INDEX IF NOT EXISTS ix_items_presupuesto_cat_jornal ON items_presupuesto(categoria_jornal_id);",
        "CREATE INDEX IF NOT EXISTS ix_categorias_jornal_org ON categorias_jornal(organizacion_id);",
        "CREATE INDEX IF NOT EXISTS ix_categorias_jornal_activo ON categorias_jornal(activo);",
    ]:
        try:
            db.session.execute(db.text(idx_sql))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"[WARN] indice: {e}")

    # Seed: categorias jornal globales sugeridas por OBYRA con valores UOCRA
    # Zona A vigentes (paritaria abril 2026, jornal de 8h, basico sin antiguedad).
    # Idempotente: solo crea si no existen, y solo actualiza precio si esta en 0
    # (no pisa valores que ya edito el superadmin).
    JORNAL_SEED_ABRIL_2026 = [
        ('Oficial Especializado', 'oficial_esp',  48088.00),
        ('Oficial',                'oficial',      41136.00),
        ('Medio Oficial',          'medio_oficial', 38016.00),
        ('Ayudante',               'ayudante',     34992.00),
        ('Sereno',                 'sereno',           0.00),  # se cobra mensual, no por jornal
    ]
    try:
        seed_globales = db.session.execute(db.text("""
            SELECT COUNT(*) FROM categorias_jornal WHERE organizacion_id IS NULL;
        """)).scalar() or 0
        for nombre, codigo, precio in JORNAL_SEED_ABRIL_2026:
            existe = db.session.execute(db.text("""
                SELECT id, precio_jornal FROM categorias_jornal
                 WHERE organizacion_id IS NULL AND LOWER(nombre) = LOWER(:nombre)
                 LIMIT 1;
            """), {'nombre': nombre}).fetchone()
            if existe:
                # Solo actualizar precio si esta en 0 (no pisar lo que el superadmin haya editado)
                if existe[1] is None or float(existe[1]) == 0.0:
                    db.session.execute(db.text("""
                        UPDATE categorias_jornal
                           SET precio_jornal = :precio,
                               codigo = COALESCE(NULLIF(codigo, ''), :codigo),
                               fuente = 'uocra',
                               vigencia_desde = '2026-04-01',
                               notas = COALESCE(NULLIF(notas, ''), 'UOCRA Zona A - basico abril 2026 (jornal 8h sin antiguedad ni cargas)')
                         WHERE id = :id;
                    """), {'precio': precio, 'codigo': codigo, 'id': existe[0]})
            else:
                db.session.execute(db.text("""
                    INSERT INTO categorias_jornal
                        (organizacion_id, nombre, codigo, precio_jornal, moneda, fuente,
                         vigencia_desde, notas, activo, created_at, updated_at)
                    VALUES
                        (NULL, :nombre, :codigo, :precio, 'ARS', 'uocra',
                         '2026-04-01',
                         'UOCRA Zona A - basico abril 2026 (jornal 8h sin antiguedad ni cargas)',
                         TRUE, NOW(), NOW());
                """), {'nombre': nombre, 'codigo': codigo, 'precio': precio})
        db.session.commit()
        print(f"[OK] Seed categorias jornal globales (UOCRA Zona A abril 2026)")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Seed categorias jornal: {e}")

    print("[OK] Migracion runtime: categorias_jornal + columnas MO en items_presupuesto")

    # =====================================================
    # 2026-04-29: Tabla variaciones_cac_pendientes
    # Cada vez que el scraper detecta un boletin Camarco nuevo, registra aca
    # la variacion mensual. El superadmin la aplica/descarta desde la UI.
    # `db.create_all()` la crea por modelo en Railway. Aca solo aseguramos
    # tabla via SQL para entornos sin create_all.
    # =====================================================
    try:
        db.session.execute(db.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='variaciones_cac_pendientes') THEN
                CREATE TABLE variaciones_cac_pendientes (
                    id SERIAL PRIMARY KEY,
                    periodo DATE NOT NULL,
                    porcentaje_mo NUMERIC(6, 2),
                    porcentaje_general NUMERIC(6, 2),
                    indice_general NUMERIC(15, 2),
                    indice_mo NUMERIC(15, 2),
                    fuente_url VARCHAR(500),
                    fuente_titulo VARCHAR(255),
                    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                    detectado_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    aplicado_at TIMESTAMP,
                    aplicado_por_id INTEGER REFERENCES usuarios(id),
                    descartado_motivo TEXT,
                    CONSTRAINT uq_variacion_cac_periodo UNIQUE (periodo)
                );
                CREATE INDEX ix_variaciones_cac_estado ON variaciones_cac_pendientes(estado);
            END IF;
        END $$;
        """))
        db.session.commit()
        print("[OK] tabla variaciones_cac_pendientes asegurada")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] variaciones_cac_pendientes: {e}")

    # =====================================================
    # 2026-04-29: Seed superadmin OBYRA
    # Asegura que los duenios del sistema tengan is_super_admin=True.
    # Idempotente: solo updatea si esta en False.
    # =====================================================
    try:
        # Debug: mostrar quienes ya son super_admin para detectar mismatches.
        admins_actuales = db.session.execute(db.text("""
            SELECT email, is_super_admin FROM usuarios
             WHERE is_super_admin = TRUE
                OR LOWER(email) LIKE '%obyra%'
                OR LOWER(email) LIKE '%brenda%'
             ORDER BY email;
        """)).fetchall()
        if admins_actuales:
            print(f"[DEBUG] Usuarios candidatos a super_admin (antes del seed):")
            for row in admins_actuales:
                print(f"        {row[0]!r}  is_super_admin={row[1]}")

        result = db.session.execute(db.text("""
            UPDATE usuarios
               SET is_super_admin = TRUE
             WHERE LOWER(email) IN (
                'admin@obyra.com',
                'brenda@gmail.com',
                'obyra.servicios@gmail.com'
             )
               AND (is_super_admin IS NULL OR is_super_admin = FALSE);
        """))
        db.session.commit()
        if result.rowcount:
            print(f"[OK] Marcados como super_admin: {result.rowcount} usuario(s)")
        elif not admins_actuales:
            print("[INFO] Seed super_admin: no se encontro ningun usuario con email matcheable.")
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Seed super_admin: {e}")

    # =====================================================
    # 2026-04-29: Seed Directorio Global de Proveedores OBYRA
    # Carga los 303 proveedores del Excel curado por OBYRA con scope='global'.
    # Solo corre si todavia no estan cargados (chequea por count >= 50).
    # =====================================================
    try:
        from seeds.proveedores_globales_seed import seed_proveedores_globales
        seed_proveedores_globales(db)
    except Exception as e:
        db.session.rollback()
        print(f"[WARN] Seed Directorio Global: {e}")
