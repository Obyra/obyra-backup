from app import db
import os
from datetime import date, timedelta, datetime
from flask import current_app
from sqlalchemy import inspect

# ---------------------- Helpers de compatibilidad/defensa ----------------------

def _backend():
    return db.engine.url.get_backend_name()

def _is_pg():
    return _backend() == "postgresql"

def _set_search_path(conn):
    """Solo en Postgres: fuerza esquema app primero."""
    if _is_pg():
        conn.exec_driver_sql("SET search_path TO app, public")

def _table_exists(conn, table_name, schema="app"):
    """
    Chequea existencia de tabla de forma portable.
    - En PG usa to_regclass('schema.table')
    - En SQLite usa inspector
    """
    try:
        if _is_pg():
            return bool(conn.exec_driver_sql(
                "SELECT to_regclass(%s)", (f"{schema}.{table_name}",)
            ).scalar())
        else:
            insp = inspect(conn)
            return table_name in set(insp.get_table_names())
    except Exception:
        return False

def _columns(conn, table_name):
    """Devuelve set de columnas de una tabla o set() si no existe."""
    try:
        insp = inspect(conn)
        return {c["name"] for c in insp.get_columns(table_name)}
    except Exception:
        return set()

def _ensure_instance_dir():
    os.makedirs("instance/migrations", exist_ok=True)

def _log_ok(msg):
    if current_app:
        current_app.logger.info(msg)

def _log_ex(msg):
    if current_app:
        current_app.logger.exception(msg)

# ------------------------------ Migraciones runtime ----------------------------

def ensure_avance_audit_columns():
    """Add audit columns to tarea_avances table if they don't exist (solo SQLite)."""
    if _backend() != "sqlite":
        return

    _ensure_instance_dir()
    sentinel = "instance/migrations/20250910_add_avance_audit_cols.done"
    if os.path.exists(sentinel):
        return

    try:
        with db.engine.begin() as conn:
            cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(tarea_avances)").fetchall()]
            if "cantidad_ingresada" not in cols:
                conn.exec_driver_sql("ALTER TABLE tarea_avances ADD COLUMN cantidad_ingresada NUMERIC")
            if "unidad_ingresada" not in cols:
                conn.exec_driver_sql("ALTER TABLE tarea_avances ADD COLUMN unidad_ingresada VARCHAR(10)")
        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Migration completed: added audit columns to tarea_avances")
    except Exception:
        _log_ex("❌ Migration failed: add avance audit columns")


def ensure_presupuesto_state_columns():
    """Estado de presupuestos (idempotente, no-op si tabla no existe)."""
    _ensure_instance_dir()
    sentinel = "instance/migrations/20250316_presupuesto_states.done"
    if os.path.exists(sentinel):
        return

    try:
        with db.engine.begin() as conn:
            _set_search_path(conn)
            if not _table_exists(conn, "presupuestos"):
                print("[SKIP] presupuestos no existe; salto state columns.")
                return

            columns = _columns(conn, "presupuestos")
            stmts = []
            if "estado" not in columns:
                coltype = "VARCHAR(20)" if _is_pg() else "TEXT"
                stmts.append(f"ALTER TABLE presupuestos ADD COLUMN estado {coltype} DEFAULT 'borrador'")
            if "perdido_motivo" not in columns:
                stmts.append("ALTER TABLE presupuestos ADD COLUMN perdido_motivo TEXT")
            if "perdido_fecha" not in columns:
                coltype = "TIMESTAMP" if _is_pg() else "DATETIME"
                stmts.append(f"ALTER TABLE presupuestos ADD COLUMN perdido_fecha {coltype}")
            if "deleted_at" not in columns:
                coltype = "TIMESTAMP" if _is_pg() else "DATETIME"
                stmts.append(f"ALTER TABLE presupuestos ADD COLUMN deleted_at {coltype}")
            for s in stmts:
                conn.exec_driver_sql(s)

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

        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Migration completed: presupuesto state columns ready")
    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        _log_ex("❌ Migration failed: presupuesto state columns")
        raise


def ensure_item_presupuesto_stage_columns():
    """Columns etapa_id / origen en items_presupuesto (no-op si no existe)."""
    _ensure_instance_dir()
    sentinel = "instance/migrations/20250317_item_stage_cols.done"
    if os.path.exists(sentinel):
        return

    try:
        with db.engine.begin() as conn:
            _set_search_path(conn)
            if not _table_exists(conn, "items_presupuesto"):
                print("[SKIP] items_presupuesto no existe; salto stage cols.")
                return

            columns = _columns(conn, "items_presupuesto")
            if "etapa_id" not in columns:
                conn.exec_driver_sql("ALTER TABLE items_presupuesto ADD COLUMN etapa_id INTEGER")
            if "origen" not in columns:
                coltype = "VARCHAR(20)" if _is_pg() else "VARCHAR(20)"
                conn.exec_driver_sql(f"ALTER TABLE items_presupuesto ADD COLUMN origen {coltype} DEFAULT 'manual'")

            conn.exec_driver_sql("UPDATE items_presupuesto SET origen = COALESCE(NULLIF(origen, ''), 'manual')")

        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Migration completed: item presupuesto stage columns ensured")
    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        _log_ex("❌ Migration failed: item presupuesto stage columns")
        raise


def ensure_presupuesto_validity_columns():
    """
    Asegura vigencia_* en presupuestos. Si la tabla no existe aún, NO rompe: no-op.
    """
    _ensure_instance_dir()
    legacy_sentinel = "instance/migrations/20250318_presupuesto_validity.done"
    sentinel = "instance/migrations/20250319_presupuesto_validity_v2.done"

    try:
        with db.engine.begin() as conn:
            _set_search_path(conn)

            # Si no existe la tabla, no hacemos nada (clave para tu error actual)
            if not _table_exists(conn, "presupuestos"):
                print("[SKIP] presupuestos no existe; salto runtime patch de vigencia.")
                # Si el sentinel viejo existiera, no nos importa por ahora
                return

            existing = _columns(conn, "presupuestos")
            required = {"vigencia_dias", "fecha_vigencia", "vigencia_bloqueada"}
            missing = required - existing

            # Re-ejecución si hacía falta (cuando venías de legacy sentinel)
            if missing and os.path.exists(legacy_sentinel):
                os.remove(legacy_sentinel)

            # Si ya está todo y existe sentinel nuevo, salir
            if not missing and os.path.exists(sentinel):
                return

            if "vigencia_dias" not in existing:
                conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN vigencia_dias INTEGER DEFAULT 30")
            if "fecha_vigencia" not in existing:
                conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN fecha_vigencia DATE")
            if "vigencia_bloqueada" not in existing:
                if _is_pg():
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN vigencia_bloqueada BOOLEAN DEFAULT FALSE")
                else:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN vigencia_bloqueada INTEGER DEFAULT 0")

            # Backfill seguro
            coalesce_literal = "FALSE" if _is_pg() else "0"
            rows = conn.exec_driver_sql(
                f"SELECT id, fecha, vigencia_dias, COALESCE(vigencia_bloqueada, {coalesce_literal}) FROM presupuestos"
            ).fetchall()

            if _is_pg():
                upd = "UPDATE presupuestos SET vigencia_dias = %s, fecha_vigencia = %s, vigencia_bloqueada = %s WHERE id = %s"
            else:
                upd = "UPDATE presupuestos SET vigencia_dias = ?, fecha_vigencia = ?, vigencia_bloqueada = ? WHERE id = ?"

            for presupuesto_id, fecha_valor, vigencia_valor, bloqueada in rows:
                dias = vigencia_valor if vigencia_valor and vigencia_valor > 0 else 30
                dias = 1 if dias < 1 else (180 if dias > 180 else dias)

                if not fecha_valor:
                    fecha_base = date.today()
                elif isinstance(fecha_valor, str):
                    try:
                        fecha_base = date.fromisoformat(fecha_valor)
                    except ValueError:
                        fecha_base = date.today()
                else:
                    fecha_base = fecha_valor

                fecha_vig = fecha_base + timedelta(days=dias)
                bloqueada_flag = bool(bloqueada)
                if not _is_pg():
                    bloqueada_flag = 1 if bloqueada_flag else 0

                conn.exec_driver_sql(upd, (dias, fecha_vig, bloqueada_flag, presupuesto_id))

        if os.path.exists(legacy_sentinel):
            os.remove(legacy_sentinel)
        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Migration completed: presupuesto validity columns ensured")
    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        _log_ex("❌ Migration failed: presupuesto validity columns")
        raise


def ensure_inventory_package_columns():
    """Config de package_options en inventory_item (no-op si la tabla no existe)."""
    _ensure_instance_dir()
    sentinel = "instance/migrations/20250912_inventory_package_options.done"
    if os.path.exists(sentinel):
        return

    try:
        with db.engine.begin() as conn:
            _set_search_path(conn)
            if not _table_exists(conn, "inventory_item"):
                print("[SKIP] inventory_item no existe; salto package_options.")
                return

            columns = _columns(conn, "inventory_item")
            if "package_options" not in columns:
                conn.exec_driver_sql("ALTER TABLE inventory_item ADD COLUMN package_options TEXT")

        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Migration completed: inventory item package options column ready")
    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        _log_ex("❌ Migration failed: inventory item package options column")
        raise


def ensure_inventory_location_columns():
    """Metadata de depósitos/obras en warehouse (no-op si la tabla no existe)."""
    _ensure_instance_dir()
    sentinel = "instance/migrations/20250915_inventory_location_type.done"
    if os.path.exists(sentinel):
        return

    try:
        with db.engine.begin() as conn:
            _set_search_path(conn)
            if not _table_exists(conn, "warehouse"):
                print("[SKIP] warehouse no existe; salto location type.")
                return

            columns = _columns(conn, "warehouse")
            if "tipo" not in columns:
                coltype = "VARCHAR(20)" if _is_pg() else "TEXT"
                conn.exec_driver_sql(f"ALTER TABLE warehouse ADD COLUMN tipo {coltype} DEFAULT 'deposito'")

            conn.exec_driver_sql("UPDATE warehouse SET tipo = COALESCE(NULLIF(tipo, ''), 'deposito')")

        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Migration completed: warehouse location type column ready")
    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        _log_ex("❌ Migration failed: warehouse location type column")
        raise


def ensure_exchange_currency_columns():
    """
    Tablas de FX/indices y columnas monetarias.
    Si presupuestos/items no existen aún, se omiten esas ALTER/UPDATE sin romper.
    """
    _ensure_instance_dir()
    sentinel = "instance/migrations/20250321_exchange_currency_fx_cac.done"
    if os.path.exists(sentinel):
        return

    try:
        with db.engine.begin() as conn:
            _set_search_path(conn)

            # Tablas maestras (siempre se pueden crear)
            if _is_pg():
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

            # Defaults de created/updated en pricing_indices (idempotente)
            pricing_cols = _columns(conn, "pricing_indices")
            if "created_at" not in pricing_cols:
                col = "TIMESTAMP NOT NULL DEFAULT NOW()" if _is_pg() else "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                conn.exec_driver_sql(f"ALTER TABLE pricing_indices ADD COLUMN created_at {col}")
            if "updated_at" not in pricing_cols:
                col = "TIMESTAMP NOT NULL DEFAULT NOW()" if _is_pg() else "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                conn.exec_driver_sql(f"ALTER TABLE pricing_indices ADD COLUMN updated_at {col}")
            conn.exec_driver_sql(
                "UPDATE pricing_indices SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP), updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)"
            )
            if _is_pg():
                conn.exec_driver_sql("ALTER TABLE pricing_indices ALTER COLUMN created_at SET DEFAULT NOW()")
                conn.exec_driver_sql("ALTER TABLE pricing_indices ALTER COLUMN updated_at SET DEFAULT NOW()")

            # ALTER en presupuestos/items solo si existen
            if _table_exists(conn, "presupuestos"):
                pcols = _columns(conn, "presupuestos")
                if "currency" not in pcols:
                    col = "VARCHAR(3) DEFAULT 'ARS'"
                    conn.exec_driver_sql(f"ALTER TABLE presupuestos ADD COLUMN currency {col}")
                if "exchange_rate_id" not in pcols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN exchange_rate_id INTEGER")
                if "exchange_rate_value" not in pcols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN exchange_rate_value NUMERIC(18,6)")
                if "exchange_rate_provider" not in pcols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN exchange_rate_provider VARCHAR(50)")
                if "exchange_rate_fetched_at" not in pcols:
                    col = "TIMESTAMP" if _is_pg() else "DATETIME"
                    conn.exec_driver_sql(f"ALTER TABLE presupuestos ADD COLUMN exchange_rate_fetched_at {col}")
                if "exchange_rate_as_of" not in pcols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN exchange_rate_as_of DATE")
                if "tasa_usd_venta" not in pcols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN tasa_usd_venta NUMERIC(10,4)")
                if "indice_cac_valor" not in pcols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN indice_cac_valor NUMERIC(12,2)")
                if "indice_cac_fecha" not in pcols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN indice_cac_fecha DATE")
                conn.exec_driver_sql("UPDATE presupuestos SET currency = COALESCE(NULLIF(currency, ''), 'ARS')")

            if _table_exists(conn, "items_presupuesto"):
                icols = _columns(conn, "items_presupuesto")
                if "currency" not in icols:
                    conn.exec_driver_sql("ALTER TABLE items_presupuesto ADD COLUMN currency VARCHAR(3) DEFAULT 'ARS'")
                if "price_unit_currency" not in icols:
                    conn.exec_driver_sql("ALTER TABLE items_presupuesto ADD COLUMN price_unit_currency NUMERIC(15,2)")
                if "total_currency" not in icols:
                    conn.exec_driver_sql("ALTER TABLE items_presupuesto ADD COLUMN total_currency NUMERIC(15,2)")
                if "price_unit_ars" not in icols:
                    conn.exec_driver_sql("ALTER TABLE items_presupuesto ADD COLUMN price_unit_ars NUMERIC(15,2)")
                if "total_ars" not in icols:
                    conn.exec_driver_sql("ALTER TABLE items_presupuesto ADD COLUMN total_ars NUMERIC(15,2)")
                conn.exec_driver_sql("UPDATE items_presupuesto SET currency = COALESCE(NULLIF(currency, ''), 'ARS')")
                conn.exec_driver_sql(
                    "UPDATE items_presupuesto SET price_unit_currency = COALESCE(price_unit_currency, precio_unitario), total_currency = COALESCE(total_currency, total)"
                )

            # Catálogos (si existen)
            for t in ("materiales", "mano_obra", "equipos"):
                if _table_exists(conn, t):
                    ccols = _columns(conn, t)
                    currency_sql = "VARCHAR(3) DEFAULT 'ARS'" if _is_pg() else "TEXT DEFAULT 'ARS'"
                    fx_rate_sql = "NUMERIC(18,6)"
                    fx_source_sql = "VARCHAR(100)" if _is_pg() else "TEXT"
                    fx_date_sql = "DATE"
                    if "currency_code" not in ccols:
                        conn.exec_driver_sql(f"ALTER TABLE {t} ADD COLUMN currency_code {currency_sql}")
                    if "fx_rate" not in ccols:
                        conn.exec_driver_sql(f"ALTER TABLE {t} ADD COLUMN fx_rate {fx_rate_sql}")
                    if "fx_source" not in ccols:
                        conn.exec_driver_sql(f"ALTER TABLE {t} ADD COLUMN fx_source {fx_source_sql}")
                    if "fx_date" not in ccols:
                        conn.exec_driver_sql(f"ALTER TABLE {t} ADD COLUMN fx_date {fx_date_sql}")

            # Seed mínimo CAC
            exists_cac = conn.exec_driver_sql("SELECT COUNT(1) FROM pricing_indices WHERE name = 'CAC'").scalar()
            if not exists_cac:
                now = datetime.utcnow()
                if _is_pg():
                    conn.exec_driver_sql(
                        "INSERT INTO pricing_indices (name, value, valid_from, notes, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s)",
                        ("CAC", 1.0, date.today(), "Valor inicial CAC", now, now),
                    )
                else:
                    conn.exec_driver_sql(
                        "INSERT INTO pricing_indices (name, value, valid_from, notes, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                        ("CAC", 1.0, date.today(), "Valor inicial CAC", now, now),
                    )

        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Migration completed: exchange rates and currency columns ready")
    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        _log_ex("❌ Migration failed: exchange rates and currency columns")
        raise


def ensure_geocode_columns():
    """Columnas de geocodificación en obras/presupuestos (no-op si tablas faltan)."""
    _ensure_instance_dir()
    sentinel = "instance/migrations/20250320_geocode_columns.done"
    if os.path.exists(sentinel):
        return

    try:
        with db.engine.begin() as conn:
            _set_search_path(conn)

            # Cache (model) siempre checkfirst
            from models import GeocodeCache  # lazy import
            GeocodeCache.__table__.create(bind=conn, checkfirst=True)

            if _table_exists(conn, "obras"):
                obras_cols = _columns(conn, "obras")
                if "direccion_normalizada" not in obras_cols:
                    conn.exec_driver_sql("ALTER TABLE obras ADD COLUMN direccion_normalizada TEXT")
                if "geocode_place_id" not in obras_cols:
                    conn.exec_driver_sql("ALTER TABLE obras ADD COLUMN geocode_place_id TEXT")
                if "geocode_provider" not in obras_cols:
                    conn.exec_driver_sql("ALTER TABLE obras ADD COLUMN geocode_provider TEXT")
                if "geocode_status" not in obras_cols:
                    col = "TEXT DEFAULT 'pending'"
                    conn.exec_driver_sql(f"ALTER TABLE obras ADD COLUMN geocode_status {col}")
                if "geocode_raw" not in obras_cols:
                    conn.exec_driver_sql("ALTER TABLE obras ADD COLUMN geocode_raw TEXT")
                if "geocode_actualizado" not in obras_cols:
                    col = "TIMESTAMP" if _is_pg() else "DATETIME"
                    conn.exec_driver_sql(f"ALTER TABLE obras ADD COLUMN geocode_actualizado {col}")
                conn.exec_driver_sql(
                    "UPDATE obras SET geocode_status = COALESCE(NULLIF(geocode_status, ''), 'pending')"
                )
            else:
                print("[SKIP] obras no existe; salto geocode en obras.")

            if _table_exists(conn, "presupuestos"):
                presup_cols = _columns(conn, "presupuestos")
                if "ubicacion_texto" not in presup_cols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN ubicacion_texto TEXT")
                if "ubicacion_normalizada" not in presup_cols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN ubicacion_normalizada TEXT")
                if "geo_latitud" not in presup_cols:
                    col = "NUMERIC(10,8)" if _is_pg() else "NUMERIC"
                    conn.exec_driver_sql(f"ALTER TABLE presupuestos ADD COLUMN geo_latitud {col}")
                if "geo_longitud" not in presup_cols:
                    col = "NUMERIC(11,8)" if _is_pg() else "NUMERIC"
                    conn.exec_driver_sql(f"ALTER TABLE presupuestos ADD COLUMN geo_longitud {col}")
                if "geocode_place_id" not in presup_cols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN geocode_place_id TEXT")
                if "geocode_provider" not in presup_cols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN geocode_provider TEXT")
                if "geocode_status" not in presup_cols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN geocode_status TEXT DEFAULT 'pending'")
                if "geocode_raw" not in presup_cols:
                    conn.exec_driver_sql("ALTER TABLE presupuestos ADD COLUMN geocode_raw TEXT")
                if "geocode_actualizado" not in presup_cols:
                    col = "TIMESTAMP" if _is_pg() else "DATETIME"
                    conn.exec_driver_sql(f"ALTER TABLE presupuestos ADD COLUMN geocode_actualizado {col}")
                conn.exec_driver_sql(
                    "UPDATE presupuestos SET geocode_status = COALESCE(NULLIF(geocode_status, ''), 'pending')"
                )
            else:
                print("[SKIP] presupuestos no existe; salto geocode en presupuestos.")

        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Geocoding columns ensured")
    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        _log_ex("❌ Migration failed: geocoding columns")
        raise


def ensure_org_memberships_table():
    """Crea/ajusta org_memberships y backfill, si las tablas base existen."""
    _ensure_instance_dir()
    sentinel = "instance/migrations/20250321_org_memberships_v2.done"
    if os.path.exists(sentinel):
        return

    try:
        with db.engine.begin() as conn:
            _set_search_path(conn)
            insp = inspect(conn)
            tables = set(insp.get_table_names())

            if "usuarios" in tables:
                usuario_columns = _columns(conn, "usuarios")
                if "primary_org_id" not in usuario_columns:
                    conn.exec_driver_sql("ALTER TABLE usuarios ADD COLUMN primary_org_id INTEGER")
                conn.exec_driver_sql(
                    """
                    UPDATE usuarios
                    SET primary_org_id = organizacion_id
                    WHERE primary_org_id IS NULL AND organizacion_id IS NOT NULL
                    """
                )

            # Crear/ajustar org_memberships
            if "org_memberships" not in tables:
                if _is_pg():
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
                columns = _columns(conn, "org_memberships")
                alters = []
                if "role" not in columns:
                    col = "VARCHAR(20)" if _is_pg() else "TEXT"
                    alters.append(f"ALTER TABLE org_memberships ADD COLUMN role {col} DEFAULT 'operario'")
                if "status" not in columns:
                    col = "VARCHAR(20)" if _is_pg() else "TEXT"
                    alters.append(f"ALTER TABLE org_memberships ADD COLUMN status {col} DEFAULT 'pending'")
                if "archived" not in columns:
                    col = "BOOLEAN" if _is_pg() else "INTEGER"
                    defv = "FALSE" if _is_pg() else "0"
                    alters.append(f"ALTER TABLE org_memberships ADD COLUMN archived {col} DEFAULT {defv}")
                if "archived_at" not in columns:
                    col = "TIMESTAMP" if _is_pg() else "DATETIME"
                    alters.append(f"ALTER TABLE org_memberships ADD COLUMN archived_at {col}")
                if "invited_by" not in columns:
                    alters.append("ALTER TABLE org_memberships ADD COLUMN invited_by INTEGER")
                if "invited_at" not in columns:
                    col = "TIMESTAMP" if _is_pg() else "DATETIME"
                    alters.append(f"ALTER TABLE org_memberships ADD COLUMN invited_at {col} DEFAULT CURRENT_TIMESTAMP")
                if "accepted_at" not in columns:
                    col = "TIMESTAMP" if _is_pg() else "DATETIME"
                    alters.append(f"ALTER TABLE org_memberships ADD COLUMN accepted_at {col}")
                for s in alters:
                    conn.exec_driver_sql(s)

            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_membership_user ON org_memberships(user_id)")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_membership_org ON org_memberships(org_id)")

            # Backfill desde usuarios si existen ambas tablas
            if "usuarios" in tables:
                if _is_pg():
                    conn.exec_driver_sql(
                        """
                        INSERT INTO org_memberships (org_id, user_id, role, status, archived, invited_at, accepted_at)
                        SELECT u.organizacion_id,
                               u.id,
                               CASE WHEN u.rol IN ('administrador','admin','administrador_general') THEN 'admin' ELSE 'operario' END,
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
                               CASE WHEN u.rol IN ('administrador','admin','administrador_general') THEN 'admin' ELSE 'operario' END,
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

        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Migration completed: org_memberships table ready")
    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        _log_ex("❌ Migration failed: org_memberships table")
        raise


def ensure_work_certification_tables():
    """Tablas de certificaciones y pagos (crea si faltan; idempotente)."""
    _ensure_instance_dir()
    sentinel = "instance/migrations/20250901_work_certifications.done"
    if os.path.exists(sentinel):
        return

    try:
        with db.engine.begin() as conn:
            _set_search_path(conn)
            insp = inspect(conn)
            tables = set(insp.get_table_names())

            def num(p, s):
                return f"NUMERIC({p},{s})" if _is_pg() else "NUMERIC"

            def ts():
                return "TIMESTAMP" if _is_pg() else "DATETIME"

            # work_certifications
            if "work_certifications" not in tables:
                if _is_pg():
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
                cols = _columns(conn, "work_certifications")
                alters = []
                if "moneda_base" not in cols:
                    col = "VARCHAR(3)" if _is_pg() else "TEXT"
                    alters.append(f"ALTER TABLE work_certifications ADD COLUMN moneda_base {col} DEFAULT 'ARS'")
                if "tc_usd" not in cols:
                    alters.append(f"ALTER TABLE work_certifications ADD COLUMN tc_usd {num(12,4)}")
                if "indice_cac" not in cols:
                    alters.append(f"ALTER TABLE work_certifications ADD COLUMN indice_cac {num(12,4)}")
                if "notas" not in cols:
                    alters.append("ALTER TABLE work_certifications ADD COLUMN notas TEXT")
                if "approved_at" not in cols:
                    alters.append(f"ALTER TABLE work_certifications ADD COLUMN approved_at {ts()}")
                if "updated_at" not in cols:
                    alters.append(f"ALTER TABLE work_certifications ADD COLUMN updated_at {ts()} DEFAULT CURRENT_TIMESTAMP")
                for s in alters:
                    conn.exec_driver_sql(s)

            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_work_certifications_obra_estado ON work_certifications(obra_id, estado)"
            )

            # work_certification_items
            if "work_certification_items" not in tables:
                if _is_pg():
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
                cols = _columns(conn, "work_certification_items")
                if "created_at" not in cols:
                    conn.exec_driver_sql(f"ALTER TABLE work_certification_items ADD COLUMN created_at {ts()}")

            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_work_certification_items_certificacion ON work_certification_items(certificacion_id)"
            )

            # work_payments
            if "work_payments" not in tables:
                if _is_pg():
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
                cols = _columns(conn, "work_payments")
                if "tc_usd_pago" not in cols:
                    conn.exec_driver_sql(f"ALTER TABLE work_payments ADD COLUMN tc_usd_pago {num(12,4)}")
                if "comprobante_url" not in cols:
                    conn.exec_driver_sql("ALTER TABLE work_payments ADD COLUMN comprobante_url TEXT")
                if "notas" not in cols:
                    conn.exec_driver_sql("ALTER TABLE work_payments ADD COLUMN notas TEXT")
                if "updated_at" not in cols:
                    conn.exec_driver_sql(f"ALTER TABLE work_payments ADD COLUMN updated_at {ts()} DEFAULT CURRENT_TIMESTAMP")

            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_work_payments_certificacion ON work_payments(certificacion_id)")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_work_payments_estado ON work_payments(estado)")

        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Work certification tables ensured")
    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        _log_ex("❌ Migration failed: work certification tables")
        raise


def ensure_wizard_budget_tables():
    """Tablas para el wizard del presupuestador (creación idempotente)."""
    _ensure_instance_dir()
    sentinel = "instance/migrations/20250330_wizard_budget_tables.done"
    if os.path.exists(sentinel):
        return

    try:
        with db.engine.begin() as conn:
            _set_search_path(conn)
            if _is_pg():
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
            _log_ex("❌ Error seeding wizard baseline coefficients")
            raise

        with open(sentinel, "w") as f:
            f.write("ok")
        _log_ok("✅ Wizard budget tables ensured and seeded")
    except Exception:
        if os.path.exists(sentinel):
            os.remove(sentinel)
        _log_ex("❌ Migration failed: wizard budget tables")
        raise
