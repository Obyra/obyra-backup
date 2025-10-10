from app import db
import os
from datetime import date, timedelta, datetime
from flask import current_app
from sqlalchemy import inspect

def ensure_avance_audit_columns():
    """Add audit columns to tarea_avances table if they don't exist"""
    if db.engine.url.get_backend_name() != 'sqlite':
        return
    
    os.makedirs('instance/migrations', exist_ok=True)
    sentinel = 'instance/migrations/20250910_add_avance_audit_cols.done'
    
    if os.path.exists(sentinel):
        return
    
    try:
        with db.engine.begin() as conn:  # connection-level txn, autocommit on success
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(tarea_avances)").fetchall()]
            
            if 'cantidad_ingresada' not in cols:
                conn.exec_driver_sql("ALTER TABLE tarea_avances ADD COLUMN cantidad_ingresada NUMERIC")
            
            if 'unidad_ingresada' not in cols:
                conn.exec_driver_sql("ALTER TABLE tarea_avances ADD COLUMN unidad_ingresada VARCHAR(10)")
        
        with open(sentinel, 'w') as f:
            f.write('ok')
            
        if current_app:
            current_app.logger.info("✅ Migration completed: added audit columns to tarea_avances")
            
    except Exception:
        # log but don't leave partial sentinel
        if current_app:
            current_app.logger.exception('❌ Migration failed: add avance audit columns')


def ensure_presupuesto_state_columns():
    """Ensure presupuesto state management columns exist and are backfilled."""
    os.makedirs('instance/migrations', exist_ok=True)
    sentinel = 'instance/migrations/20250316_presupuesto_states.done'

    if os.path.exists(sentinel):
        return

    try:
        engine = db.engine
        with engine.begin() as conn:
            inspector = inspect(conn)
            try:
                columns = {col['name'] for col in inspector.get_columns('presupuestos')}
            except Exception:
                columns = set()

            statements = []

            if 'estado' not in columns:
                if engine.url.get_backend_name() == 'postgresql':
                    statements.append("ALTER TABLE presupuestos ADD COLUMN estado VARCHAR(20) DEFAULT 'borrador'")
                else:
                    statements.append("ALTER TABLE presupuestos ADD COLUMN estado TEXT DEFAULT 'borrador'")
            else:
                # Even if the column exists, make sure NULL/empty rows are updated below
                pass

            if 'perdido_motivo' not in columns:
                statements.append("ALTER TABLE presupuestos ADD COLUMN perdido_motivo TEXT")

            if 'perdido_fecha' not in columns:
                if engine.url.get_backend_name() == 'postgresql':
                    statements.append("ALTER TABLE presupuestos ADD COLUMN perdido_fecha TIMESTAMP")
                else:
                    statements.append("ALTER TABLE presupuestos ADD COLUMN perdido_fecha DATETIME")

            if 'deleted_at' not in columns:
                if engine.url.get_backend_name() == 'postgresql':
                    statements.append("ALTER TABLE presupuestos ADD COLUMN deleted_at TIMESTAMP")
                else:
                    statements.append("ALTER TABLE presupuestos ADD COLUMN deleted_at DATETIME")

            for stmt in statements:
                conn.exec_driver_sql(stmt)

            # Backfill estado column after creation/update
            conn.exec_driver_sql(
                """
                UPDATE presupuestos
                SET estado = CASE
                    WHEN confirmado_como_obra = 1 OR confirmado_como_obra = TRUE THEN 'confirmado'
                    ELSE 'borrador'
                END
                WHERE estado IS NULL OR estado = ''
                """
            )

        with open(sentinel, 'w') as f:
            f.write('ok')

        if current_app:
            current_app.logger.info('✅ Migration completed: presupuesto state columns ready')

    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        if current_app:
            current_app.logger.exception('❌ Migration failed: presupuesto state columns')
        raise


def ensure_item_presupuesto_stage_columns():
    """Ensure ItemPresupuesto tiene columnas para vincular etapas y origen."""
    os.makedirs('instance/migrations', exist_ok=True)
    sentinel = 'instance/migrations/20250317_item_stage_cols.done'

    if os.path.exists(sentinel):
        return

    try:
        engine = db.engine
        with engine.begin() as conn:
            inspector = inspect(conn)
            try:
                columns = {col['name'] for col in inspector.get_columns('items_presupuesto')}
            except Exception:
                columns = set()

            statements = []

            if 'etapa_id' not in columns:
                statements.append("ALTER TABLE items_presupuesto ADD COLUMN etapa_id INTEGER")

            if 'origen' not in columns:
                default_clause = "DEFAULT 'manual'" if engine.url.get_backend_name() != 'postgresql' else "DEFAULT 'manual'"
                statements.append(f"ALTER TABLE items_presupuesto ADD COLUMN origen VARCHAR(20) {default_clause}")

            for stmt in statements:
                conn.exec_driver_sql(stmt)

            conn.exec_driver_sql(
                """
                UPDATE items_presupuesto
                SET origen = COALESCE(NULLIF(origen, ''), 'manual')
                """
            )

        with open(sentinel, 'w') as f:
            f.write('ok')

        if current_app:
            current_app.logger.info('✅ Migration completed: item presupuesto stage columns ensured')

    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        if current_app:
            current_app.logger.exception('❌ Migration failed: item presupuesto stage columns')
        raise


def ensure_presupuesto_validity_columns():
    """Ensure presupuesto vigencia columns exist and are populated."""
    os.makedirs('instance/migrations', exist_ok=True)

    engine = db.engine
    backend = engine.url.get_backend_name()

    # Previous sentinel (sin vigencia_bloqueada) that may exist en instalaciones viejas
    legacy_sentinel = 'instance/migrations/20250318_presupuesto_validity.done'
    sentinel = 'instance/migrations/20250319_presupuesto_validity_v2.done'

    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            try:
                existing_columns = {col['name'] for col in inspector.get_columns('presupuestos')}
            except Exception:
                existing_columns = set()

        required_columns = {'vigencia_dias', 'fecha_vigencia', 'vigencia_bloqueada'}
        missing_columns = required_columns - existing_columns

        # Si el sentinel viejo existe pero faltan columnas nuevas, forzamos re-ejecución
        if missing_columns and os.path.exists(legacy_sentinel):
            os.remove(legacy_sentinel)

        if not missing_columns and os.path.exists(sentinel):
            return

        with engine.begin() as conn:
            statements = []

            if 'vigencia_dias' not in existing_columns:
                statements.append("ALTER TABLE presupuestos ADD COLUMN vigencia_dias INTEGER DEFAULT 30")

            if 'fecha_vigencia' not in existing_columns:
                if backend == 'postgresql':
                    statements.append("ALTER TABLE presupuestos ADD COLUMN fecha_vigencia DATE")
                else:
                    statements.append("ALTER TABLE presupuestos ADD COLUMN fecha_vigencia DATE")

            if 'vigencia_bloqueada' not in existing_columns:
                if backend == 'postgresql':
                    statements.append("ALTER TABLE presupuestos ADD COLUMN vigencia_bloqueada BOOLEAN DEFAULT TRUE")
                else:
                    statements.append("ALTER TABLE presupuestos ADD COLUMN vigencia_bloqueada INTEGER DEFAULT 1")

            for stmt in statements:
                conn.exec_driver_sql(stmt)

            # Recalcular vigencia para todos los presupuestos (nuevos o existentes)
            rows = conn.exec_driver_sql(
                "SELECT id, fecha, vigencia_dias, COALESCE(vigencia_bloqueada, 1) FROM presupuestos"
            ).fetchall()

            if backend == 'postgresql':
                update_sql = (
                    "UPDATE presupuestos SET vigencia_dias = %s, fecha_vigencia = %s, vigencia_bloqueada = %s WHERE id = %s"
                )
            else:
                update_sql = (
                    "UPDATE presupuestos SET vigencia_dias = ?, fecha_vigencia = ?, vigencia_bloqueada = ? WHERE id = ?"
                )

            for presupuesto_id, fecha_valor, vigencia_valor, bloqueada in rows:
                dias = vigencia_valor if vigencia_valor and vigencia_valor > 0 else 30
                if dias < 1:
                    dias = 1
                elif dias > 180:
                    dias = 180

                if not fecha_valor:
                    fecha_base = date.today()
                elif isinstance(fecha_valor, str):
                    try:
                        fecha_base = date.fromisoformat(fecha_valor)
                    except ValueError:
                        fecha_base = date.today()
                else:
                    fecha_base = fecha_valor

                fecha_vigencia = fecha_base + timedelta(days=dias)
                bloqueada_flag = bool(bloqueada)
                if backend != 'postgresql':
                    bloqueada_flag = 1 if bloqueada_flag else 0

                conn.exec_driver_sql(update_sql, (dias, fecha_vigencia, bloqueada_flag, presupuesto_id))

        # Guardamos sentinel actualizado y eliminamos el anterior si quedó
        if os.path.exists(legacy_sentinel):
            os.remove(legacy_sentinel)

        with open(sentinel, 'w') as f:
            f.write('ok')

        if current_app:
            current_app.logger.info('✅ Migration completed: presupuesto validity columns ensured')

    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        if current_app:
            current_app.logger.exception('❌ Migration failed: presupuesto validity columns')
        raise


def ensure_inventory_package_columns():
    """Ensure inventory items support configurable package options."""

    os.makedirs('instance/migrations', exist_ok=True)
    sentinel = 'instance/migrations/20250912_inventory_package_options.done'

    if os.path.exists(sentinel):
        return

    engine = db.engine
    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            try:
                columns = {col['name'] for col in inspector.get_columns('inventory_item')}
            except Exception:
                columns = set()

            if 'package_options' not in columns:
                conn.exec_driver_sql("ALTER TABLE inventory_item ADD COLUMN package_options TEXT")

        with open(sentinel, 'w') as sentinel_file:
            sentinel_file.write('ok')

        if current_app:
            current_app.logger.info('✅ Migration completed: inventory item package options column ready')

    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        if current_app:
            current_app.logger.exception('❌ Migration failed: inventory item package options column')
        raise


def ensure_exchange_currency_columns():
    """Ensure exchange rate tables and currency columns exist."""

    os.makedirs('instance/migrations', exist_ok=True)
    sentinel = 'instance/migrations/20250321_exchange_currency_fx_cac.done'

    if os.path.exists(sentinel):
        return

    engine = db.engine
    backend = engine.url.get_backend_name()

    try:
        with engine.begin() as conn:
            if backend == 'postgresql':
                conn.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS exchange_rates (
                        id SERIAL PRIMARY KEY,
                        provider VARCHAR(50) NOT NULL,
                        base_currency VARCHAR(3) NOT NULL DEFAULT 'ARS',
                        quote_currency VARCHAR(3) NOT NULL DEFAULT 'USD',
                        rate NUMERIC(18,6) NOT NULL,
                        as_of_date DATE NOT NULL DEFAULT CURRENT_DATE,
                        fetched_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        source_url VARCHAR(255),
                        notes VARCHAR(255),
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_exchange_rate_daily UNIQUE(provider, base_currency, quote_currency, as_of_date)
                    )
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS cac_indices (
                        id SERIAL PRIMARY KEY,
                        year INTEGER NOT NULL,
                        month INTEGER NOT NULL,
                        value NUMERIC(12,2) NOT NULL,
                        provider VARCHAR(50) NOT NULL,
                        source_url VARCHAR(255),
                        fetched_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_cac_index_period_provider UNIQUE(year, month, provider)
                    )
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS pricing_indices (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(50) NOT NULL,
                        value NUMERIC(18,6) NOT NULL,
                        valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
                        notes VARCHAR(255),
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_pricing_indices_name_valid_from UNIQUE(name, valid_from)
                    )
                    """
                )
            else:
                conn.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS exchange_rates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        provider TEXT NOT NULL,
                        base_currency TEXT NOT NULL DEFAULT 'ARS',
                        quote_currency TEXT NOT NULL DEFAULT 'USD',
                        rate NUMERIC(18,6) NOT NULL,
                        as_of_date DATE NOT NULL DEFAULT CURRENT_DATE,
                        fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        source_url TEXT,
                        notes TEXT,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(provider, base_currency, quote_currency, as_of_date)
                    )
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS cac_indices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        year INTEGER NOT NULL,
                        month INTEGER NOT NULL,
                        value NUMERIC(12,2) NOT NULL,
                        provider TEXT NOT NULL,
                        source_url TEXT,
                        fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(year, month, provider)
                    )
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS pricing_indices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        value NUMERIC(18,6) NOT NULL,
                        valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
                        notes TEXT,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(name, valid_from)
                    )
                    """
                )

            inspector = inspect(conn)
            try:
                exchange_columns = {col['name'] for col in inspector.get_columns('exchange_rates')}
            except Exception:
                exchange_columns = set()

            try:
                pricing_columns = {col['name'] for col in inspector.get_columns('pricing_indices')}
            except Exception:
                pricing_columns = set()

            if 'created_at' not in pricing_columns:
                if backend == 'postgresql':
                    conn.exec_driver_sql(
                        "ALTER TABLE pricing_indices ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT NOW()"
                    )
                else:
                    conn.exec_driver_sql(
                        "ALTER TABLE pricing_indices ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    )

            if 'updated_at' not in pricing_columns:
                if backend == 'postgresql':
                    conn.exec_driver_sql(
                        "ALTER TABLE pricing_indices ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT NOW()"
                    )
                else:
                    conn.exec_driver_sql(
                        "ALTER TABLE pricing_indices ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    )

            conn.exec_driver_sql(
                """
                UPDATE pricing_indices
                   SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
                       updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
                """
            )

            if backend == 'postgresql':
                conn.exec_driver_sql(
                    "ALTER TABLE pricing_indices ALTER COLUMN created_at SET DEFAULT NOW()"
                )
                conn.exec_driver_sql(
                    "ALTER TABLE pricing_indices ALTER COLUMN updated_at SET DEFAULT NOW()"
                )

            if 'as_of_date' not in exchange_columns:
                conn.exec_driver_sql("ALTER TABLE exchange_rates ADD COLUMN as_of_date DATE")

            try:
                presupuesto_columns = {col['name'] for col in inspector.get_columns('presupuestos')}
            except Exception:
                presupuesto_columns = set()

            try:
                item_columns = {col['name'] for col in inspector.get_columns('items_presupuesto')}
            except Exception:
                item_columns = set()

            pres_alter_statements = []
            if 'currency' not in presupuesto_columns:
                default_clause = "DEFAULT 'ARS'" if backend != 'postgresql' else "DEFAULT 'ARS'"
                pres_alter_statements.append(f"ALTER TABLE presupuestos ADD COLUMN currency VARCHAR(3) {default_clause}")
            if 'exchange_rate_id' not in presupuesto_columns:
                pres_alter_statements.append("ALTER TABLE presupuestos ADD COLUMN exchange_rate_id INTEGER")
            if 'exchange_rate_value' not in presupuesto_columns:
                pres_alter_statements.append("ALTER TABLE presupuestos ADD COLUMN exchange_rate_value NUMERIC(18,6)")
            if 'exchange_rate_provider' not in presupuesto_columns:
                pres_alter_statements.append("ALTER TABLE presupuestos ADD COLUMN exchange_rate_provider VARCHAR(50)")
            if 'exchange_rate_fetched_at' not in presupuesto_columns:
                column_type = 'TIMESTAMP' if backend == 'postgresql' else 'DATETIME'
                pres_alter_statements.append(f"ALTER TABLE presupuestos ADD COLUMN exchange_rate_fetched_at {column_type}")
            if 'exchange_rate_as_of' not in presupuesto_columns:
                column_type = 'DATE'
                pres_alter_statements.append(f"ALTER TABLE presupuestos ADD COLUMN exchange_rate_as_of {column_type}")
            if 'tasa_usd_venta' not in presupuesto_columns:
                pres_alter_statements.append("ALTER TABLE presupuestos ADD COLUMN tasa_usd_venta NUMERIC(10,4)")
            if 'indice_cac_valor' not in presupuesto_columns:
                pres_alter_statements.append("ALTER TABLE presupuestos ADD COLUMN indice_cac_valor NUMERIC(12,2)")
            if 'indice_cac_fecha' not in presupuesto_columns:
                pres_alter_statements.append("ALTER TABLE presupuestos ADD COLUMN indice_cac_fecha DATE")

            for stmt in pres_alter_statements:
                conn.exec_driver_sql(stmt)

            item_alter_statements = []
            if 'currency' not in item_columns:
                default_clause = "DEFAULT 'ARS'" if backend != 'postgresql' else "DEFAULT 'ARS'"
                item_alter_statements.append(f"ALTER TABLE items_presupuesto ADD COLUMN currency VARCHAR(3) {default_clause}")
            if 'price_unit_currency' not in item_columns:
                item_alter_statements.append("ALTER TABLE items_presupuesto ADD COLUMN price_unit_currency NUMERIC(15,2)")
            if 'total_currency' not in item_columns:
                item_alter_statements.append("ALTER TABLE items_presupuesto ADD COLUMN total_currency NUMERIC(15,2)")
            if 'price_unit_ars' not in item_columns:
                item_alter_statements.append("ALTER TABLE items_presupuesto ADD COLUMN price_unit_ars NUMERIC(15,2)")
            if 'total_ars' not in item_columns:
                item_alter_statements.append("ALTER TABLE items_presupuesto ADD COLUMN total_ars NUMERIC(15,2)")

            for stmt in item_alter_statements:
                conn.exec_driver_sql(stmt)

            currency_column_sql = "VARCHAR(3) DEFAULT 'ARS'" if backend == 'postgresql' else "TEXT DEFAULT 'ARS'"
            fx_rate_sql = "NUMERIC(18,6)"
            fx_source_sql = "VARCHAR(100)" if backend == 'postgresql' else "TEXT"
            fx_date_sql = 'DATE'

            for catalog_table in ('materiales', 'mano_obra', 'equipos'):
                try:
                    catalog_columns = {col['name'] for col in inspector.get_columns(catalog_table)}
                except Exception:
                    # Tabla inexistente en esta instalación, continuar sin error
                    continue

                catalog_alter_statements = []
                if 'currency_code' not in catalog_columns:
                    catalog_alter_statements.append(
                        f"ALTER TABLE {catalog_table} ADD COLUMN currency_code {currency_column_sql}"
                    )
                if 'fx_rate' not in catalog_columns:
                    catalog_alter_statements.append(
                        f"ALTER TABLE {catalog_table} ADD COLUMN fx_rate {fx_rate_sql}"
                    )
                if 'fx_source' not in catalog_columns:
                    catalog_alter_statements.append(
                        f"ALTER TABLE {catalog_table} ADD COLUMN fx_source {fx_source_sql}"
                    )
                if 'fx_date' not in catalog_columns:
                    catalog_alter_statements.append(
                        f"ALTER TABLE {catalog_table} ADD COLUMN fx_date {fx_date_sql}"
                    )

                for stmt in catalog_alter_statements:
                    conn.exec_driver_sql(stmt)

            # Backfill defaults
            conn.exec_driver_sql(
                """
                UPDATE presupuestos
                SET currency = COALESCE(NULLIF(currency, ''), 'ARS')
                """
            )
            conn.exec_driver_sql(
                """
                UPDATE items_presupuesto
                SET currency = COALESCE(NULLIF(currency, ''), 'ARS')
                """
            )
            conn.exec_driver_sql(
                """
                UPDATE items_presupuesto
                SET price_unit_currency = COALESCE(price_unit_currency, precio_unitario),
                    total_currency = COALESCE(total_currency, total)
                """
            )

            # Seed CAC index if empty
            existing_index = conn.exec_driver_sql(
                "SELECT COUNT(1) FROM pricing_indices WHERE name = 'CAC'"
            ).scalar()
            if not existing_index:
                now = datetime.utcnow()
                if backend == 'postgresql':
                    insert_sql = (
                        "INSERT INTO pricing_indices (name, value, valid_from, notes, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)"
                    )
                    conn.exec_driver_sql(
                        insert_sql,
                        ('CAC', 1.0, date.today(), 'Valor inicial CAC', now, now),
                    )
                else:
                    conn.exec_driver_sql(
                        "INSERT INTO pricing_indices (name, value, valid_from, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        ('CAC', 1.0, date.today(), 'Valor inicial CAC', now, now),
                    )

        with open(sentinel, 'w') as f:
            f.write('ok')

        if current_app:
            current_app.logger.info('✅ Migration completed: exchange rates and currency columns ready')

    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        if current_app:
            current_app.logger.exception('❌ Migration failed: exchange rates and currency columns')
        raise


def ensure_geocode_columns():
    """Ensure geocoding metadata tables and columns exist."""

    os.makedirs('instance/migrations', exist_ok=True)
    sentinel = 'instance/migrations/20250320_geocode_columns.done'

    if os.path.exists(sentinel):
        return

    engine = db.engine
    backend = engine.url.get_backend_name()

    try:
        with engine.begin() as conn:
            inspector = inspect(conn)

            try:
                obras_columns = {col['name'] for col in inspector.get_columns('obras')}
            except Exception:
                obras_columns = set()

            try:
                presup_columns = {col['name'] for col in inspector.get_columns('presupuestos')}
            except Exception:
                presup_columns = set()

            from models import GeocodeCache  # Lazy import to avoid circular deps

            GeocodeCache.__table__.create(bind=conn, checkfirst=True)

            obras_statements = []
            if 'direccion_normalizada' not in obras_columns:
                obras_statements.append("ALTER TABLE obras ADD COLUMN direccion_normalizada TEXT")
            if 'geocode_place_id' not in obras_columns:
                obras_statements.append("ALTER TABLE obras ADD COLUMN geocode_place_id TEXT")
            if 'geocode_provider' not in obras_columns:
                obras_statements.append("ALTER TABLE obras ADD COLUMN geocode_provider TEXT")
            if 'geocode_status' not in obras_columns:
                default_clause = "DEFAULT 'pending'" if backend != 'postgresql' else "DEFAULT 'pending'"
                obras_statements.append(f"ALTER TABLE obras ADD COLUMN geocode_status TEXT {default_clause}")
            if 'geocode_raw' not in obras_columns:
                obras_statements.append("ALTER TABLE obras ADD COLUMN geocode_raw TEXT")
            if 'geocode_actualizado' not in obras_columns:
                column_type = 'TIMESTAMP' if backend == 'postgresql' else 'DATETIME'
                obras_statements.append(f"ALTER TABLE obras ADD COLUMN geocode_actualizado {column_type}")

            for stmt in obras_statements:
                conn.exec_driver_sql(stmt)

            presup_statements = []
            if 'ubicacion_texto' not in presup_columns:
                presup_statements.append("ALTER TABLE presupuestos ADD COLUMN ubicacion_texto TEXT")
            if 'ubicacion_normalizada' not in presup_columns:
                presup_statements.append("ALTER TABLE presupuestos ADD COLUMN ubicacion_normalizada TEXT")
            if 'geo_latitud' not in presup_columns:
                column_def = "NUMERIC(10,8)" if backend == 'postgresql' else "NUMERIC"
                presup_statements.append(f"ALTER TABLE presupuestos ADD COLUMN geo_latitud {column_def}")
            if 'geo_longitud' not in presup_columns:
                column_def = "NUMERIC(11,8)" if backend == 'postgresql' else "NUMERIC"
                presup_statements.append(f"ALTER TABLE presupuestos ADD COLUMN geo_longitud {column_def}")
            if 'geocode_place_id' not in presup_columns:
                presup_statements.append("ALTER TABLE presupuestos ADD COLUMN geocode_place_id TEXT")
            if 'geocode_provider' not in presup_columns:
                presup_statements.append("ALTER TABLE presupuestos ADD COLUMN geocode_provider TEXT")
            if 'geocode_status' not in presup_columns:
                default_clause = "DEFAULT 'pending'" if backend != 'postgresql' else "DEFAULT 'pending'"
                presup_statements.append(f"ALTER TABLE presupuestos ADD COLUMN geocode_status TEXT {default_clause}")
            if 'geocode_raw' not in presup_columns:
                presup_statements.append("ALTER TABLE presupuestos ADD COLUMN geocode_raw TEXT")
            if 'geocode_actualizado' not in presup_columns:
                column_type = 'TIMESTAMP' if backend == 'postgresql' else 'DATETIME'
                presup_statements.append(f"ALTER TABLE presupuestos ADD COLUMN geocode_actualizado {column_type}")

            for stmt in presup_statements:
                conn.exec_driver_sql(stmt)

            conn.exec_driver_sql(
                "UPDATE obras SET geocode_status = COALESCE(NULLIF(geocode_status, ''), 'pending')"
            )
            conn.exec_driver_sql(
                "UPDATE presupuestos SET geocode_status = COALESCE(NULLIF(geocode_status, ''), 'pending')"
            )

        with open(sentinel, 'w') as handler:
            handler.write('ok')

        if current_app:
            current_app.logger.info('✅ Geocoding columns ensured')

    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        if current_app:
            current_app.logger.exception('❌ Migration failed: geocoding columns')
        raise


def ensure_org_memberships_table():
    """Ensure org_memberships table exists and memberships are backfilled."""
    os.makedirs('instance/migrations', exist_ok=True)
    sentinel = 'instance/migrations/20250321_org_memberships_v2.done'

    if os.path.exists(sentinel):
        return

    engine = db.engine
    backend = engine.url.get_backend_name()

    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            tables = inspector.get_table_names()

            if 'usuarios' in tables:
                usuario_columns = {col['name'] for col in inspector.get_columns('usuarios')}
                if 'primary_org_id' not in usuario_columns:
                    conn.exec_driver_sql("ALTER TABLE usuarios ADD COLUMN primary_org_id INTEGER")

                conn.exec_driver_sql(
                    """
                    UPDATE usuarios
                    SET primary_org_id = organizacion_id
                    WHERE primary_org_id IS NULL AND organizacion_id IS NOT NULL
                    """
                )

            if 'org_memberships' not in tables:
                if backend == 'postgresql':
                    conn.exec_driver_sql(
                        """
                        CREATE TABLE IF NOT EXISTS org_memberships (
                            id SERIAL PRIMARY KEY,
                            org_id INTEGER NOT NULL,
                            user_id INTEGER NOT NULL,
                            role VARCHAR(20) NOT NULL DEFAULT 'operario',
                            status VARCHAR(20) NOT NULL DEFAULT 'pending',
                            archived BOOLEAN NOT NULL DEFAULT FALSE,
                            archived_at TIMESTAMP,
                            invited_by INTEGER,
                            invited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            accepted_at TIMESTAMP,
                            CONSTRAINT uq_membership_org_user UNIQUE (org_id, user_id)
                        )
                        """
                    )
                else:
                    conn.exec_driver_sql(
                        """
                        CREATE TABLE IF NOT EXISTS org_memberships (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            org_id INTEGER NOT NULL,
                            user_id INTEGER NOT NULL,
                            role TEXT NOT NULL DEFAULT 'operario',
                            status TEXT NOT NULL DEFAULT 'pending',
                            archived INTEGER NOT NULL DEFAULT 0,
                            archived_at DATETIME,
                            invited_by INTEGER,
                            invited_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            accepted_at DATETIME,
                            CONSTRAINT uq_membership_org_user UNIQUE (org_id, user_id)
                        )
                        """
                    )
            else:
                columns = {col['name'] for col in inspector.get_columns('org_memberships')}
                alterations = []
                if 'role' not in columns:
                    column_type = 'VARCHAR(20)' if backend == 'postgresql' else 'TEXT'
                    alterations.append(f"ALTER TABLE org_memberships ADD COLUMN role {column_type} DEFAULT 'operario'")
                if 'status' not in columns:
                    column_type = 'VARCHAR(20)' if backend == 'postgresql' else 'TEXT'
                    alterations.append(f"ALTER TABLE org_memberships ADD COLUMN status {column_type} DEFAULT 'pending'")
                if 'archived' not in columns:
                    column_type = 'BOOLEAN' if backend == 'postgresql' else 'INTEGER'
                    alterations.append(f"ALTER TABLE org_memberships ADD COLUMN archived {column_type} DEFAULT 0")
                if 'archived_at' not in columns:
                    column_type = 'TIMESTAMP' if backend == 'postgresql' else 'DATETIME'
                    alterations.append(f"ALTER TABLE org_memberships ADD COLUMN archived_at {column_type}")
                if 'invited_by' not in columns:
                    alterations.append("ALTER TABLE org_memberships ADD COLUMN invited_by INTEGER")
                if 'invited_at' not in columns:
                    column_type = 'TIMESTAMP' if backend == 'postgresql' else 'DATETIME'
                    alterations.append(f"ALTER TABLE org_memberships ADD COLUMN invited_at {column_type} DEFAULT CURRENT_TIMESTAMP")
                if 'accepted_at' not in columns:
                    column_type = 'TIMESTAMP' if backend == 'postgresql' else 'DATETIME'
                    alterations.append(f"ALTER TABLE org_memberships ADD COLUMN accepted_at {column_type}")

                for statement in alterations:
                    conn.exec_driver_sql(statement)

            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_membership_user ON org_memberships(user_id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_membership_org ON org_memberships(org_id)"
            )

            if backend == 'postgresql':
                conn.exec_driver_sql(
                    """
                    INSERT INTO org_memberships (org_id, user_id, role, status, archived, invited_at, accepted_at)
                    SELECT u.organizacion_id,
                           u.id,
                           CASE WHEN u.rol IN ('administrador', 'admin', 'administrador_general') THEN 'admin' ELSE 'operario' END,
                           CASE WHEN u.activo IS NULL OR u.activo = TRUE THEN 'active' ELSE 'inactive' END,
                           FALSE,
                           CURRENT_TIMESTAMP,
                           CASE WHEN u.activo IS NULL OR u.activo = TRUE THEN CURRENT_TIMESTAMP ELSE NULL END
                    FROM usuarios u
                    WHERE u.organizacion_id IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM org_memberships m WHERE m.org_id = u.organizacion_id AND m.user_id = u.id
                    )
                    """
                )
            else:
                conn.exec_driver_sql(
                    """
                    INSERT INTO org_memberships (org_id, user_id, role, status, archived, invited_at, accepted_at)
                    SELECT u.organizacion_id,
                           u.id,
                           CASE WHEN u.rol IN ('administrador', 'admin', 'administrador_general') THEN 'admin' ELSE 'operario' END,
                           CASE WHEN u.activo IS NULL OR u.activo = 1 THEN 'active' ELSE 'inactive' END,
                           0,
                           CURRENT_TIMESTAMP,
                           CASE WHEN u.activo IS NULL OR u.activo = 1 THEN CURRENT_TIMESTAMP ELSE NULL END
                    FROM usuarios u
                    WHERE u.organizacion_id IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM org_memberships m WHERE m.org_id = u.organizacion_id AND m.user_id = u.id
                    )
                    """
                )

        with open(sentinel, 'w') as handle:
            handle.write('ok')

        if current_app:
            current_app.logger.info('✅ Migration completed: org_memberships table ready')

    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        if current_app:
            current_app.logger.exception('❌ Migration failed: org_memberships table')
        raise


def ensure_work_certification_tables():
    """Ensure work certification & payment tables exist."""
    os.makedirs('instance/migrations', exist_ok=True)
    sentinel = 'instance/migrations/20250901_work_certifications.done'

    if os.path.exists(sentinel):
        return

    engine = db.engine
    backend = engine.url.get_backend_name()

    def numeric_type(precision, scale):
        if backend == 'postgresql':
            return f'NUMERIC({precision},{scale})'
        return 'NUMERIC'

    def timestamp_type():
        return 'TIMESTAMP' if backend == 'postgresql' else 'DATETIME'

    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            tables = set(inspector.get_table_names())

            if 'work_certifications' not in tables:
                if backend == 'postgresql':
                    conn.exec_driver_sql(
                        """
                        CREATE TABLE IF NOT EXISTS work_certifications (
                            id SERIAL PRIMARY KEY,
                            obra_id INTEGER NOT NULL,
                            organizacion_id INTEGER NOT NULL,
                            periodo_desde DATE,
                            periodo_hasta DATE,
                            porcentaje_avance NUMERIC(7,3) DEFAULT 0,
                            monto_certificado_ars NUMERIC(15,2) DEFAULT 0,
                            monto_certificado_usd NUMERIC(15,2) DEFAULT 0,
                            moneda_base VARCHAR(3) DEFAULT 'ARS',
                            tc_usd NUMERIC(12,4),
                            indice_cac NUMERIC(12,4),
                            estado VARCHAR(20) DEFAULT 'borrador',
                            notas TEXT,
                            created_by_id INTEGER,
                            approved_by_id INTEGER,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            approved_at TIMESTAMP
                        )
                        """
                    )
                else:
                    conn.exec_driver_sql(
                        """
                        CREATE TABLE IF NOT EXISTS work_certifications (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            obra_id INTEGER NOT NULL,
                            organizacion_id INTEGER NOT NULL,
                            periodo_desde DATE,
                            periodo_hasta DATE,
                            porcentaje_avance NUMERIC DEFAULT 0,
                            monto_certificado_ars NUMERIC DEFAULT 0,
                            monto_certificado_usd NUMERIC DEFAULT 0,
                            moneda_base TEXT DEFAULT 'ARS',
                            tc_usd NUMERIC,
                            indice_cac NUMERIC,
                            estado TEXT DEFAULT 'borrador',
                            notas TEXT,
                            created_by_id INTEGER,
                            approved_by_id INTEGER,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            approved_at DATETIME
                        )
                        """
                    )
            else:
                columns = {col['name'] for col in inspector.get_columns('work_certifications')}
                alterations = []
                for name, col_type, default in [
                    ('moneda_base', 'VARCHAR(3)' if backend == 'postgresql' else 'TEXT', "DEFAULT 'ARS'"),
                    ('tc_usd', numeric_type(12, 4), None),
                    ('indice_cac', numeric_type(12, 4), None),
                    ('notas', 'TEXT', None),
                    ('approved_at', timestamp_type(), None),
                    ('updated_at', timestamp_type(), "DEFAULT CURRENT_TIMESTAMP"),
                ]:
                    if name not in columns:
                        stmt = f"ALTER TABLE work_certifications ADD COLUMN {name} {col_type}"
                        if default:
                            stmt += f" {default}"
                        alterations.append(stmt)
                for stmt in alterations:
                    conn.exec_driver_sql(stmt)

            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_work_certifications_obra_estado ON work_certifications(obra_id, estado)"
            )

            if 'work_certification_items' not in tables:
                if backend == 'postgresql':
                    conn.exec_driver_sql(
                        """
                        CREATE TABLE IF NOT EXISTS work_certification_items (
                            id SERIAL PRIMARY KEY,
                            certificacion_id INTEGER NOT NULL,
                            etapa_id INTEGER,
                            tarea_id INTEGER,
                            porcentaje_aplicado NUMERIC(7,3) DEFAULT 0,
                            monto_ars NUMERIC(15,2) DEFAULT 0,
                            monto_usd NUMERIC(15,2) DEFAULT 0,
                            fuente_avance VARCHAR(20) DEFAULT 'manual',
                            resumen_avance TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                else:
                    conn.exec_driver_sql(
                        """
                        CREATE TABLE IF NOT EXISTS work_certification_items (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            certificacion_id INTEGER NOT NULL,
                            etapa_id INTEGER,
                            tarea_id INTEGER,
                            porcentaje_aplicado NUMERIC DEFAULT 0,
                            monto_ars NUMERIC DEFAULT 0,
                            monto_usd NUMERIC DEFAULT 0,
                            fuente_avance TEXT DEFAULT 'manual',
                            resumen_avance TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
            else:
                columns = {col['name'] for col in inspector.get_columns('work_certification_items')}
                if 'created_at' not in columns:
                    conn.exec_driver_sql(
                        f"ALTER TABLE work_certification_items ADD COLUMN created_at {timestamp_type()}"
                    )

            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_work_certification_items_certificacion ON work_certification_items(certificacion_id)"
            )

            if 'work_payments' not in tables:
                if backend == 'postgresql':
                    conn.exec_driver_sql(
                        """
                        CREATE TABLE IF NOT EXISTS work_payments (
                            id SERIAL PRIMARY KEY,
                            certificacion_id INTEGER,
                            obra_id INTEGER NOT NULL,
                            organizacion_id INTEGER NOT NULL,
                            operario_id INTEGER,
                            metodo_pago VARCHAR(30) NOT NULL,
                            moneda VARCHAR(3) DEFAULT 'ARS',
                            monto NUMERIC(15,2) NOT NULL,
                            tc_usd_pago NUMERIC(12,4),
                            fecha_pago DATE DEFAULT CURRENT_DATE,
                            comprobante_url TEXT,
                            notas TEXT,
                            estado VARCHAR(20) DEFAULT 'pendiente',
                            created_by_id INTEGER,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                else:
                    conn.exec_driver_sql(
                        """
                        CREATE TABLE IF NOT EXISTS work_payments (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            certificacion_id INTEGER,
                            obra_id INTEGER NOT NULL,
                            organizacion_id INTEGER NOT NULL,
                            operario_id INTEGER,
                            metodo_pago TEXT NOT NULL,
                            moneda TEXT DEFAULT 'ARS',
                            monto NUMERIC NOT NULL,
                            tc_usd_pago NUMERIC,
                            fecha_pago DATE DEFAULT CURRENT_DATE,
                            comprobante_url TEXT,
                            notas TEXT,
                            estado TEXT DEFAULT 'pendiente',
                            created_by_id INTEGER,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
            else:
                columns = {col['name'] for col in inspector.get_columns('work_payments')}
                for name, col_type, default in [
                    ('tc_usd_pago', numeric_type(12, 4), None),
                    ('comprobante_url', 'TEXT', None),
                    ('notas', 'TEXT', None),
                    ('updated_at', timestamp_type(), "DEFAULT CURRENT_TIMESTAMP"),
                ]:
                    if name not in columns:
                        stmt = f"ALTER TABLE work_payments ADD COLUMN {name} {col_type}"
                        if default:
                            stmt += f" {default}"
                        conn.exec_driver_sql(stmt)

            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_work_payments_certificacion ON work_payments(certificacion_id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_work_payments_estado ON work_payments(estado)"
            )

        with open(sentinel, 'w') as handle:
            handle.write('ok')

        if current_app:
            current_app.logger.info('✅ Work certification tables ensured')

    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        if current_app:
            current_app.logger.exception('❌ Migration failed: work certification tables')
        raise


def ensure_wizard_budget_tables():
    """Create tables para variantes y coeficientes del presupuestador wizard."""

    os.makedirs('instance/migrations', exist_ok=True)
    sentinel = 'instance/migrations/20250330_wizard_budget_tables.done'

    if os.path.exists(sentinel):
        return

    engine = db.engine
    backend = engine.url.get_backend_name()

    try:
        with engine.begin() as conn:
            if backend == 'postgresql':
                conn.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS wizard_stage_variants (
                        id SERIAL PRIMARY KEY,
                        stage_slug VARCHAR(80) NOT NULL,
                        variant_key VARCHAR(80) NOT NULL,
                        nombre VARCHAR(120) NOT NULL,
                        descripcion VARCHAR(255),
                        is_default BOOLEAN DEFAULT FALSE,
                        metadata JSONB,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_wizard_stage_variant UNIQUE(stage_slug, variant_key)
                    )
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS wizard_stage_coefficients (
                        id SERIAL PRIMARY KEY,
                        stage_slug VARCHAR(80) NOT NULL,
                        variant_id INTEGER REFERENCES wizard_stage_variants(id) ON DELETE CASCADE,
                        unit VARCHAR(20) NOT NULL DEFAULT 'u',
                        quantity_metric VARCHAR(50) NOT NULL DEFAULT 'cantidad',
                        materials_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                        labor_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                        equipment_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                        currency VARCHAR(3) NOT NULL DEFAULT 'ARS',
                        source VARCHAR(80),
                        notes VARCHAR(255),
                        is_baseline BOOLEAN DEFAULT FALSE,
                        metadata JSONB,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_wizard_stage_coeff_variant UNIQUE(stage_slug, variant_id)
                    )
                    """
                )
            else:
                conn.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS wizard_stage_variants (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stage_slug TEXT NOT NULL,
                        variant_key TEXT NOT NULL,
                        nombre TEXT NOT NULL,
                        descripcion TEXT,
                        is_default INTEGER DEFAULT 0,
                        metadata TEXT,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stage_slug, variant_key)
                    )
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE TABLE IF NOT EXISTS wizard_stage_coefficients (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stage_slug TEXT NOT NULL,
                        variant_id INTEGER REFERENCES wizard_stage_variants(id) ON DELETE CASCADE,
                        unit TEXT NOT NULL DEFAULT 'u',
                        quantity_metric TEXT NOT NULL DEFAULT 'cantidad',
                        materials_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                        labor_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                        equipment_per_unit NUMERIC(18,4) NOT NULL DEFAULT 0,
                        currency TEXT NOT NULL DEFAULT 'ARS',
                        source TEXT,
                        notes TEXT,
                        is_baseline INTEGER DEFAULT 0,
                        metadata TEXT,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stage_slug, variant_id)
                    )
                    """
                )

        try:
            from services.wizard_budgeting import seed_default_coefficients_if_needed

            seed_default_coefficients_if_needed()
        except Exception:
            if current_app:
                current_app.logger.exception('❌ Error seeding wizard baseline coefficients')
            raise

        with open(sentinel, 'w') as handle:
            handle.write('ok')

        if current_app:
            current_app.logger.info('✅ Wizard budget tables ensured and seeded')

    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        if current_app:
            current_app.logger.exception('❌ Migration failed: wizard budget tables')
        raise
