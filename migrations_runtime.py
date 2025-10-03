from app import db
import os
from datetime import date, timedelta
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
    sentinel = 'instance/migrations/20250318_presupuesto_validity.done'

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

            if 'vigencia_dias' not in columns:
                default_clause = "INTEGER DEFAULT 30" if engine.url.get_backend_name() != 'postgresql' else "INTEGER DEFAULT 30"
                statements.append(f"ALTER TABLE presupuestos ADD COLUMN vigencia_dias {default_clause}")

            if 'fecha_vigencia' not in columns:
                statements.append("ALTER TABLE presupuestos ADD COLUMN fecha_vigencia DATE")

            if 'vigencia_bloqueada' not in columns:
                default_bool = 'BOOLEAN DEFAULT 1' if engine.url.get_backend_name() != 'postgresql' else 'BOOLEAN DEFAULT TRUE'
                statements.append(f"ALTER TABLE presupuestos ADD COLUMN vigencia_bloqueada {default_bool}")

            for stmt in statements:
                conn.exec_driver_sql(stmt)

            rows = conn.exec_driver_sql(
                "SELECT id, fecha, vigencia_dias, COALESCE(vigencia_bloqueada, 1) FROM presupuestos"
            ).fetchall()

            update_sqlite = (
                "UPDATE presupuestos SET vigencia_dias = ?, fecha_vigencia = ?, vigencia_bloqueada = ? WHERE id = ?"
            )
            update_pg = (
                "UPDATE presupuestos SET vigencia_dias = %s, fecha_vigencia = %s, vigencia_bloqueada = %s WHERE id = %s"
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
                    fecha_base = date.fromisoformat(fecha_valor)
                else:
                    fecha_base = fecha_valor
                fecha_vigencia = fecha_base + timedelta(days=dias)

                update_sql = update_pg if engine.url.get_backend_name() == 'postgresql' else update_sqlite
                conn.exec_driver_sql(update_sql, (dias, fecha_vigencia, bool(bloqueada), presupuesto_id))

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