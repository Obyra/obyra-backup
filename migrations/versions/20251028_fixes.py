"""normalize role_modules seq + presupuestos defaults"""

from __future__ import annotations

from alembic import op

revision = "20251028_fixes"
down_revision = "20251028_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SEQUENCE IF NOT EXISTS app.role_modules_id_seq
            AS bigint
            START WITH 1
            INCREMENT BY 1
            NO MINVALUE
            NO MAXVALUE
            CACHE 1;
        """
    )

    op.execute(
        """
        ALTER SEQUENCE app.role_modules_id_seq OWNED BY app.role_modules.id;
        ALTER TABLE app.role_modules
            ALTER COLUMN id TYPE bigint,
            ALTER COLUMN id SET DEFAULT nextval('app.role_modules_id_seq'::regclass);
        SELECT setval(
            'app.role_modules_id_seq',
            COALESCE((SELECT MAX(id) FROM app.role_modules), 1),
            (SELECT EXISTS(SELECT 1 FROM app.role_modules))
        );
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
                EXECUTE 'GRANT USAGE, SELECT, UPDATE ON SEQUENCE app.role_modules_id_seq TO app_rw';
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'obyra_app') THEN
                EXECUTE 'GRANT USAGE, SELECT, UPDATE ON SEQUENCE app.role_modules_id_seq TO obyra_app';
            END IF;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
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
            );
        UPDATE app.presupuestos
        SET vigencia_bloqueada = FALSE
        WHERE vigencia_bloqueada IS NULL;
        ALTER TABLE app.presupuestos
            ALTER COLUMN vigencia_bloqueada SET DEFAULT FALSE;
        """
    )


def downgrade() -> None:
    pass
