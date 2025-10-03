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
