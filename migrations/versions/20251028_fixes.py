"""normalize role_modules seq + presupuestos defaults (defensivo)"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

# ⚠️ mantené estos ids tal cual están en tu repo
revision = "20251028_fixes"
down_revision = "20251028_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # asegurar que todo lo que ejecuta Alembic vaya a app
    conn.execute(text("SET search_path TO app, public"))

    # ---------- role_modules (solo si existe) ----------
    exists_role_modules = conn.execute(
        text("SELECT to_regclass('app.role_modules')")
    ).scalar()

    if exists_role_modules:
        # crear/normalizar secuencia y defaults (defensivo para ownership)
        conn.execute(
            text("""
            DO $$
            BEGIN
              CREATE SEQUENCE IF NOT EXISTS app.role_modules_id_seq
                  AS bigint START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

              -- Solo alterar sequence si somos dueños de la tabla
              IF (SELECT tableowner FROM pg_tables WHERE schemaname = 'app' AND tablename = 'role_modules') = current_user THEN
                ALTER SEQUENCE app.role_modules_id_seq OWNED BY app.role_modules.id;
                ALTER TABLE app.role_modules ALTER COLUMN id TYPE BIGINT;
                ALTER TABLE app.role_modules ALTER COLUMN id SET DEFAULT nextval('app.role_modules_id_seq'::regclass);
                PERFORM setval(
                  'app.role_modules_id_seq',
                  COALESCE((SELECT MAX(id) FROM app.role_modules), 1),
                  (SELECT EXISTS(SELECT 1 FROM app.role_modules))
                );
              END IF;
            END$$;
            """)
        )
        # grants opcionales si los roles existen
        conn.execute(
            text("""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
                EXECUTE 'GRANT USAGE, SELECT, UPDATE ON SEQUENCE app.role_modules_id_seq TO app_rw';
              END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'obyra_app') THEN
                EXECUTE 'GRANT USAGE, SELECT, UPDATE ON SEQUENCE app.role_modules_id_seq TO obyra_app';
              END IF;
            END$$;
            """)
        )

    # ---------- presupuestos (solo si existe) ----------
    exists_pres = conn.execute(
        text("SELECT to_regclass('app.presupuestos')")
    ).scalar()

    if exists_pres:
        conn.execute(
            text("""
            ALTER TABLE app.presupuestos
              ALTER COLUMN vigencia_bloqueada TYPE boolean
              USING (
                CASE
                  WHEN vigencia_bloqueada IS NULL THEN FALSE
                  ELSE COALESCE(
                    NULLIF(TRIM(CAST(vigencia_bloqueada AS TEXT)), '')::boolean,
                    FALSE
                  )
                END
              )
            """)
        )
        conn.execute(text("UPDATE app.presupuestos SET vigencia_bloqueada = FALSE WHERE vigencia_bloqueada IS NULL"))
        conn.execute(text("ALTER TABLE app.presupuestos ALTER COLUMN vigencia_bloqueada SET DEFAULT FALSE"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("SET search_path TO app, public"))

    # revert mínimo y también defensivo
    exists_pres = conn.execute(text("SELECT to_regclass('app.presupuestos')")).scalar()
    if exists_pres:
        # si querés, podés omitir esta reversión; la dejo como no-op
        pass

    # no tocamos role_modules a la baja para evitar perder datos
    pass
