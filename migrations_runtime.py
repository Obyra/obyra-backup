from app import db
import os
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