"""Application factory and bootstrap helpers."""
from __future__ import annotations

try:  # pragma: no cover - optional during CLI usage
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback when dependency is absent
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

import importlib
import logging
import os
import sys
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

import click
from flask import (
    Flask,
    abort,
    flash,
    g,
    has_request_context,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.cli import AppGroup
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.routing import BuildError

from .config import AppConfig
from .extensions import db, login_manager, migrate
from models import OrgMembership

_logger = logging.getLogger(__name__)


def _ensure_utf8_io() -> None:
    """Force UTF-8 aware standard streams so CLI prints never fail."""

    target_encoding = "utf-8"
    os.environ.setdefault("PYTHONIOENCODING", target_encoding)

    if not hasattr(sys, "stdout") or not hasattr(sys, "stderr"):
        return

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding=target_encoding)
            elif hasattr(stream, "buffer"):
                import io

                stream.flush()
                wrapped = io.TextIOWrapper(
                    stream.buffer,
                    encoding=target_encoding,
                    errors="replace",
                )
                setattr(sys, name, wrapped)
        except Exception:  # pragma: no cover - defensive fallback
            continue


_ensure_utf8_io()

_builtin_print = print


def _safe_cli_print(*args, **kwargs):
    target = kwargs.get("file", sys.stdout)
    encoding = getattr(target, "encoding", None) or os.environ.get("PYTHONIOENCODING") or "utf-8"

    safe_args = []
    for arg in args:
        text = str(arg)
        try:
            text.encode(encoding, errors="strict")
        except Exception:
            text = text.encode("ascii", "ignore").decode("ascii")
        safe_args.append(text)

    _builtin_print(*safe_args, **kwargs)


print = _safe_cli_print  # type: ignore[assignment]


# ====== ORG CONTEXT (sin archivo nuevo) ======
def set_current_org(user, org_id: int):
    """Fija la organización actual en sesión y asegura membresía activa."""
    if not user or not getattr(user, "id", None):
        raise RuntimeError("Usuario no autenticado para fijar organización.")

    membership = (
        OrgMembership.query
        .filter(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == user.id,
            OrgMembership.archived.is_(False)
        )
        .first()
    )

    if not membership:
        # Crear membresía activa por defecto (o cambiar por 403 si querés estricto)
        membership = user.ensure_membership(org_id, status='active')
        db.session.commit()

    session['current_org_id'] = org_id
    return membership


def load_current_membership():
    """Carga g.current_membership en cada request según la org actual."""
    g.current_membership = None
    if not current_user.is_authenticated:
        return

    org_id = (
        session.get('current_org_id')
        or current_user.primary_org_id
        or current_user.organizacion_id
    )
    if not org_id:
        return

    membership = (
        OrgMembership.query
        .filter(
            OrgMembership.org_id == org_id,
            OrgMembership.user_id == current_user.id,
            OrgMembership.archived.is_(False)
        )
        .first()
    )
    if membership:
        g.current_membership = membership
        if session.get('current_org_id') != org_id:
            session['current_org_id'] = org_id
# ====== FIN ORG CONTEXT ======


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _import_blueprint(module_name: str, attr_name: str):
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def _resolve_login_endpoint(app: Flask) -> Optional[str]:
    candidate_endpoints = (
        "auth.login",
        "supplier_auth.login",
        "auth_login",
        "index",
    )
    for endpoint in candidate_endpoints:
        if endpoint in app.view_functions:
            return endpoint
    return None


def _resolve_login_url(app: Flask) -> str:
    endpoint = _resolve_login_endpoint(app)
    if not endpoint:
        return "/"
    try:
        if has_request_context():
            return url_for(endpoint)
        with app.test_request_context():
            return url_for(endpoint)
    except Exception:
        return "/"


def _login_redirect(app: Flask):
    return redirect(_resolve_login_url(app))


def _refresh_login_view(app: Flask) -> None:
    login_manager.login_view = _resolve_login_endpoint(app)


def _format_seed_summary(stats: dict) -> str:
    created = stats.get("created", 0)
    existing = stats.get("existing", 0)
    reactivated = stats.get("reactivated", 0)
    return f"creadas={created}, existentes={existing}, reactivadas={reactivated}"


def _register_db_cli(app: Flask) -> None:
    db_cli = AppGroup("db")

    @db_cli.command("upgrade")
    def db_upgrade():
        """Apply pending lightweight database migrations."""

        from flask_migrate import upgrade as alembic_upgrade

        with app.app_context():
            logger = app.logger
            logger.info("Running Alembic upgrade...")
            alembic_upgrade()
            logger.info("Alembic upgrade → OK")
            logger.info("Running post-upgrade runtime ensures...")

            from migrations_runtime import (
                ensure_avance_audit_columns,
                ensure_exchange_currency_columns,
                ensure_geocode_columns,
                ensure_item_presupuesto_stage_columns,
                ensure_org_memberships_table,
                ensure_presupuesto_state_columns,
                ensure_presupuesto_validity_columns,
                ensure_work_certification_tables,
            )

            ensure_avance_audit_columns()
            ensure_presupuesto_state_columns()
            ensure_item_presupuesto_stage_columns()
            ensure_presupuesto_validity_columns()
            ensure_exchange_currency_columns()
            ensure_geocode_columns()
            ensure_org_memberships_table()
            ensure_work_certification_tables()

        click.echo("[OK] Database upgraded successfully.")

    app.cli.add_command(db_cli)


def _register_fx_cli(app: Flask) -> None:
    fx_cli = AppGroup("fx")

    @fx_cli.command("update")
    @click.option("--provider", default="bna", help="Proveedor de tipo de cambio (ej. bna)")
    def fx_update(provider: str):
        provider_key = (provider or "bna").lower()

        with app.app_context():
            from services.exchange import base as exchange_base
            from services.exchange.providers import bna as bna_provider

            if provider_key != "bna":
                click.echo('[WARN] Por ahora solo se admite el proveedor "bna". Se usará Banco Nación.')
                provider_key = "bna"

            fallback_env = app.config.get("EXCHANGE_FALLBACK_RATE")
            fallback = Decimal(str(fallback_env)) if fallback_env else None

            snapshot = exchange_base.ensure_rate(
                provider_key,
                base_currency="ARS",
                quote_currency="USD",
                fetcher=bna_provider.fetch_official_rate,
                fallback_rate=fallback,
            )

            click.echo(
                "[OK] Tipo de cambio actualizado: {valor} ({prov} {fecha:%d/%m/%Y})".format(
                    valor=snapshot.value,
                    prov=snapshot.provider.upper(),
                    fecha=snapshot.as_of_date,
                )
            )

    app.cli.add_command(fx_cli)


def _register_cac_cli(app: Flask) -> None:
    cac_cli = AppGroup("cac")

    @cac_cli.command("set")
    @click.option("--value", required=True, type=float, help="Valor numérico del índice CAC")
    @click.option("--valid-from", type=click.DateTime(formats=["%Y-%m-%d"]), help="Fecha de vigencia (YYYY-MM-DD)")
    @click.option("--notes", default=None, help="Notas opcionales")
    def cac_set(value: float, valid_from, notes: Optional[str]):
        with app.app_context():
            from datetime import date

            from services.cac.cac_service import record_manual_index

            valid_date = valid_from.date() if valid_from else date.today().replace(day=1)
            registro = record_manual_index(valid_date.year, valid_date.month, Decimal(str(value)), notes)
            click.echo(
                "[OK] Índice CAC registrado: {valor} ({anio}-{mes:02d}, proveedor {prov})".format(
                    valor=registro.value,
                    anio=registro.year,
                    mes=registro.month,
                    prov=registro.provider,
                )
            )

    @cac_cli.command("refresh-current")
    def cac_refresh_current():
        with app.app_context():
            from services.cac.cac_service import get_cac_context, refresh_from_provider

            registro = refresh_from_provider()
            contexto = get_cac_context()
            if registro:
                click.echo(
                    "[OK] CAC actualizado automáticamente: {valor} ({anio}-{mes:02d})".format(
                        valor=registro.value,
                        anio=registro.year,
                        mes=registro.month,
                    )
                )
            else:
                click.echo('[WARN] No se pudo obtener el índice CAC automáticamente. Se mantiene el valor vigente.')
            click.echo(
                "[INFO] Contexto actual: valor={valor} multiplicador={mult}".format(
                    valor=contexto.value,
                    mult=contexto.multiplier,
                )
            )

    app.cli.add_command(cac_cli)


def _register_inventory_cli(app: Flask) -> None:
    @app.cli.command("seed:inventario")
    @click.option("--global", "seed_global", is_flag=True, help="Inicializa el catálogo global compartido")
    @click.option("--org", "org_identifiers", multiple=True, help="ID, slug, token o nombre de la organización a sembrar")
    @click.option("--quiet", is_flag=True, help="Oculta el detalle por categoría")
    def seed_inventario_cli(seed_global: bool, org_identifiers: Tuple[str, ...], quiet: bool) -> None:
        if not seed_global and not org_identifiers:
            raise click.ClickException("Debes indicar al menos una organización con --org o usar --global.")

        from models import Organizacion
        from seed_inventory_categories import seed_inventory_categories_for_company

        with app.app_context():
            stats = {"created": 0, "existing": 0, "reactivated": 0}

            if seed_global:
                result = seed_inventory_categories_for_company(None, quiet=quiet)
                click.echo("[INFO] Catálogo global: " + _format_seed_summary(result))
                for key in stats:
                    stats[key] += result.get(key, 0)

            if org_identifiers:
                for identifier in org_identifiers:
                    org = _resolve_cli_organization(identifier)
                    if not org:
                        click.echo(f"[WARN] Organización no encontrada: {identifier}")
                        continue
                    result = seed_inventory_categories_for_company(org.id, quiet=quiet)
                    click.echo(
                        "[INFO] Org {nombre} (ID {id}): {detalle}".format(
                            nombre=getattr(org, "nombre", "-"),
                            id=org.id,
                            detalle=_format_seed_summary(result),
                        )
                    )
                    for key in stats:
                        stats[key] += result.get(key, 0)

            click.echo("[OK] Seed completado: " + _format_seed_summary(stats))

    def _resolve_cli_organization(identifier: str):
        identifier = (identifier or "").strip()
        if not identifier:
            return None

        from models import Organizacion
        from sqlalchemy import func as sa_func

        if identifier.isdigit():
            return Organizacion.query.get(int(identifier))

        if hasattr(Organizacion, "slug"):
            org = Organizacion.query.filter_by(slug=identifier).first()
            if org:
                return org

        org = Organizacion.query.filter_by(token_invitacion=identifier).first()
        if org:
            return org

        lowered = identifier.lower()
        return (
            Organizacion.query
            .filter(sa_func.lower(Organizacion.nombre) == lowered)
            .first()
        )


def _register_clis(app: Flask) -> None:
    _register_db_cli(app)
    _register_fx_cli(app)
    _register_cac_cli(app)
    _register_inventory_cli(app)


def _register_blueprints(app: Flask) -> None:
    auth_blueprint_registered = False
    core_failures = []

    try:
        from auth import auth_bp

        app.register_blueprint(auth_bp)
        auth_blueprint_registered = True
        print("[OK] Auth blueprint registered successfully")
    except ImportError as exc:
        print(f"[WARN] Auth blueprint not available: {exc}")

    for module_name, attr_name, prefix in [
        ("obras", "obras_bp", None),
        ("reportes", "reportes_bp", None),
        ("presupuestos", "presupuestos_bp", None),
        ("marketplace", "marketplace_bp", "/marketplace"),
        ("inventario", "inventario_bp", "/inventario"),
        ("inventario_new", "inventario_new_bp", "/inventario-new"),
        ("equipos", "equipos_bp", "/equipos"),
        ("equipos_new", "equipos_new_bp", "/equipos-new"),
        ("market", "market_bp", None),
        ("orders", "orders_bp", None),
        ("seguridad_cumplimiento", "seguridad_bp", "/seguridad"),
        ("agent_local", "agent_bp", None),
        ("planes", "planes_bp", None),
        ("events_service", "events_bp", None),
        ("account", "account_bp", None),
        ("onboarding", "onboarding_bp", "/onboarding"),
    ]:
        try:
            blueprint = _import_blueprint(module_name, attr_name)
            app.register_blueprint(blueprint, url_prefix=prefix)
        except Exception as exc:  # pragma: no cover - blueprint registration best effort
            core_failures.append(f"{module_name} ({exc})")

    if core_failures:
        print("[WARN] Some core blueprints not available: " + "; ".join(core_failures))
    else:
        print("[OK] Core blueprints registered successfully")

    if app.config.get("ENABLE_REPORTS_SERVICE"):
        try:
            import matplotlib  # noqa: F401 - optional dependency probe

            reports_service_bp = _import_blueprint("reports_service", "reports_bp")
            app.register_blueprint(reports_service_bp)
            print("[OK] Reports service enabled")
        except Exception as exc:  # pragma: no cover - optional dependency guard
            app.logger.warning("Reports service disabled: %s", exc)
            app.config["ENABLE_REPORTS_SERVICE"] = False
    else:
        app.logger.info("Reports service disabled (set ENABLE_REPORTS=1 to enable)")

    if not auth_blueprint_registered:

        @app.route("/auth/login", endpoint="auth.login")
        def fallback_auth_login():
            try:
                return redirect(url_for("supplier_auth.login"))
            except BuildError:
                return "Login no disponible temporalmente.", 503

        @app.route("/auth/register", methods=["GET", "POST"], endpoint="auth.register")
        def fallback_auth_register():
            flash("El registro de usuarios no está disponible en este entorno.", "warning")
            try:
                return redirect(url_for("supplier_auth.registro"))
            except BuildError:
                return "Registro de usuarios no disponible temporalmente.", 503

    try:
        from supplier_auth import supplier_auth_bp
        from supplier_portal import supplier_portal_bp

        app.register_blueprint(supplier_auth_bp)
        app.register_blueprint(supplier_portal_bp)
        print("[OK] Supplier portal blueprints registered successfully")
    except ImportError as exc:
        print(f"[WARN] Supplier portal blueprints not available: {exc}")

    try:
        from marketplace.routes import bp as marketplace_bp

        app.register_blueprint(marketplace_bp, url_prefix="/")
        print("[OK] Marketplace blueprint registered successfully")
    except ImportError as exc:
        print(f"[WARN] Marketplace blueprint not available: {exc}")

    _refresh_login_view(app)


def _register_routes(app: Flask) -> None:
    @app.context_processor
    def inject_login_url():
        return {"login_url": _resolve_login_url(app)}

    @app.route("/", methods=["GET", "POST"])
    def index():
        if current_user.is_authenticated:
            if getattr(current_user, "role", None) == "operario":
                return redirect(url_for("obras.mis_tareas"))
            return redirect(url_for("reportes.dashboard"))

        next_page = request.values.get("next")
        form_data = {
            "email": request.form.get("email", ""),
            "remember": bool(request.form.get("remember")),
        }

        google_available = False
        login_helper = None
        try:
            from auth import google, authenticate_manual_user  # type: ignore

            google_available = bool(google)
            login_helper = authenticate_manual_user
        except ImportError:
            login_helper = None

        if request.method == "POST":
            if login_helper is None:
                flash("El módulo de autenticación no está disponible en este entorno.", "danger")
            else:
                success, payload = login_helper(
                    form_data["email"],
                    request.form.get("password", ""),
                    remember=form_data["remember"],
                )

                if success:
                    usuario = payload
                    if next_page:
                        return redirect(next_page)
                    if getattr(usuario, "role", None) == "operario":
                        return redirect(url_for("obras.mis_tareas"))
                    return redirect(url_for("reportes.dashboard"))
                else:
                    message = ""
                    category = "danger"
                    if isinstance(payload, dict):
                        message = payload.get("message", "")
                        category = payload.get("category", category)
                    else:
                        message = str(payload)
                    if message:
                        flash(message, category)

        return render_template(
            "public/home.html",
            google_available=google_available,
            form_data=form_data,
            next_value=next_page,
        )

    @app.route("/login", endpoint="auth_login")
    def legacy_login_redirect():
        return _login_redirect(app)

    @app.route("/dashboard")
    def dashboard():
        if current_user.is_authenticated:
            if getattr(current_user, "role", None) == "operario":
                return redirect(url_for("obras.mis_tareas"))
            return redirect(url_for("reportes.dashboard"))
        return _login_redirect(app)

    if "terminos" not in app.view_functions:
        app.add_url_rule(
            "/terminos",
            endpoint="terminos",
            view_func=lambda: render_template("legal/terminos.html"),
        )

    if "privacidad" not in app.view_functions:
        app.add_url_rule(
            "/privacidad",
            endpoint="privacidad",
            view_func=lambda: render_template("legal/privacidad.html"),
        )


def _register_template_filters(app: Flask) -> None:
    @app.template_filter("fecha")
    def fecha_filter(fecha):
        if fecha:
            return fecha.strftime("%d/%m/%Y")
        return ""

    @app.template_filter("moneda")
    def moneda_filter(valor, currency: str = "ARS"):
        try:
            monto = Decimal(str(valor))
        except (InvalidOperation, ValueError, TypeError):
            monto = Decimal("0")
        symbol = "US$" if (currency or "ARS").upper() == "USD" else "$"
        return f"{symbol}{monto:,.2f}"

    @app.template_filter("porcentaje")
    def porcentaje_filter(valor):
        if valor is None:
            return "0%"
        return f"{valor:.1f}%"

    @app.template_filter("numero")
    def numero_filter(valor, decimales=0):
        if valor is None:
            return "0"
        return f"{valor:,.{decimales}f}"

    @app.template_filter("estado_badge")
    def estado_badge_filter(estado):
        badges = {
            "activo": "bg-success",
            "inactivo": "bg-secondary",
            "borrador": "bg-secondary",
            "enviado": "bg-warning",
            "aprobado": "bg-success",
            "rechazado": "bg-danger",
            "perdido": "bg-dark",
            "vencido": "bg-danger",
            "eliminado": "bg-dark",
            "planificacion": "bg-secondary",
            "en_progreso": "bg-primary",
            "pausada": "bg-warning",
            "finalizada": "bg-success",
            "cancelada": "bg-danger",
        }
        return badges.get(estado, "bg-secondary")

    @app.template_filter("obtener_nombre_rol")
    def obtener_nombre_rol_filter(codigo_rol):
        try:
            from roles_construccion import obtener_nombre_rol

            return obtener_nombre_rol(codigo_rol)
        except Exception:
            return codigo_rol.replace("_", " ").title()

    @app.template_filter("from_json")
    def from_json_filter(json_str):
        if not json_str:
            return {}
        try:
            import json

            return json.loads(json_str)
        except Exception:
            return {}


def create_app(config: Optional[AppConfig] = None) -> Flask:
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    logging.basicConfig(level=logging.DEBUG)

    cfg = config or AppConfig()
    cfg.init_app(app)

    app.config["SHOW_IA_CALCULATOR_BUTTON"] = _env_flag("SHOW_IA_CALCULATOR_BUTTON", False)
    app.config["ENABLE_REPORTS_SERVICE"] = _env_flag("ENABLE_REPORTS", False)
    app.config["MAPS_PROVIDER"] = (os.environ.get("MAPS_PROVIDER") or "nominatim").strip().lower()
    app.config["MAPS_API_KEY"] = os.environ.get("MAPS_API_KEY")
    app.config["MP_ACCESS_TOKEN"] = os.getenv("MP_ACCESS_TOKEN", "").strip()
    app.config["MP_WEBHOOK_PUBLIC_URL"] = os.getenv("MP_WEBHOOK_PUBLIC_URL", "").strip()

    if not app.config["MP_ACCESS_TOKEN"]:
        app.logger.warning(
            "Mercado Pago access token (MP_ACCESS_TOKEN) is not configured; Mercado Pago operations will fail."
        )

    mp_webhook_url = app.config.get("MP_WEBHOOK_PUBLIC_URL")
    if mp_webhook_url:
        app.logger.info("MP webhook URL: %s", mp_webhook_url)
    else:
        app.logger.warning(
            "MP_WEBHOOK_PUBLIC_URL is not configured; expected path: /api/payments/mp/webhook"
        )

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db, compare_type=True, directory="alembic")

    login_manager.login_view = None
    login_manager.login_message = "Por favor inicia sesión para acceder a esta página."
    login_manager.login_message_category = "info"

    app.before_request(load_current_membership)

    _register_clis(app)
    _register_blueprints(app)
    _register_routes(app)
    _register_template_filters(app)

    return app


__all__ = ["create_app", "db", "login_manager", "migrate", "set_current_org"]
