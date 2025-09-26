# migrations_runtime.py
import os
from sqlalchemy import inspect, text
from flask import current_app, has_app_context
from app import db

def _log_info(msg: str):
    if has_app_context():
        try:
            current_app.logger.info(msg)
        except Exception:
            pass

def _log_warn(msg: str):
    if has_app_context():
        try:
            current_app.logger.warning(msg)
        except Exception:
            pass

def _log_exc(msg: str):
    if has_app_context():
        try:
            current_app.logger.exception(msg)
        except Exception:
            pass

def ensure_avance_audit_columns():
    """
    Agrega columnas de auditoría a 'tarea_avances' si hacen falta (SQLite).
    - Idempotente: solo agrega si no existen.
    - Seguro: no intenta alterar si la tabla no existe.
    - Sentinel: marca la migración aplicada en instance/migrations/.
    """
    try:
        # Solo aplica a SQLite
        if db.engine.url.get_backend_name() != "sqlite":
            return

        # Paths robustos dentro de instance/
        if has_app_context():
            base_instance = current_app.instance_path
        else:
            base_instance = os.path.join(os.getcwd(), "instance")

        mig_dir = os.path.join(base_instance, "migrations")
        os.makedirs(mig_dir, exist_ok=True)
        sentinel = os.path.join(mig_dir, "20250910_add_avance_audit_cols.done")

        # Si ya se aplicó, salir
        if os.path.exists(sentinel):
            return

        with db.engine.begin() as conn:
            insp = inspect(conn)

            # Si la tabla no existe, salimos sin romper (la crearán los modelos/migraciones)
            if "tarea_avances" not in insp.get_table_names():
                _log_warn("tarea_avances no existe aún; omito migration runtime.")
                return

            # Columnas existentes
            cols = {c["name"] for c in insp.get_columns("tarea_avances")}

            # Agregar columnas solo si faltan
            if "cantidad_ingresada" not in cols:
                conn.execute(text(
                    "ALTER TABLE tarea_avances ADD COLUMN cantidad_ingresada NUMERIC"
                ))

            if "unidad_ingresada" not in cols:
                conn.execute(text(
                    "ALTER TABLE tarea_avances ADD COLUMN unidad_ingresada VARCHAR(10)"
                ))

        # Marcamos como aplicada solo al final, si todo salió bien
        with open(sentinel, "w", encoding="utf-8") as f:
            f.write("ok")

        _log_info("✅ Migration completed: added audit columns to tarea_avances")

    except Exception:
        # No dejamos sentinel en caso de error
        try:
            if "sentinel" in locals() and os.path.exists(sentinel):
                os.remove(sentinel)
        except Exception:
            pass
        _log_exc("❌ Migration failed: add avance audit columns")
        # No re-raise para no tumbar el arranque por una migration runtime
