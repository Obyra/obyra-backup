"""
Métricas de Negocio
====================

Provee endpoints y helpers para exponer métricas operativas de OBYRA.

Métricas disponibles:
- Tenants activos (organizaciones con actividad reciente)
- Usuarios activos (login en los últimos N días)
- Distribución por plan (cuántos en standard/premium/full_premium)
- Total de obras activas
- Total de presupuestos del mes
- Latencia P50/P95/P99 de requests

Endpoints:
- GET /admin/metrics — vista HTML para super admin
- GET /admin/metrics.json — JSON para sistemas de monitoreo
- GET /admin/metrics/prometheus — formato Prometheus (opcional)

Las métricas se cachean en Redis durante 5 minutos para no impactar performance.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any


logger = logging.getLogger(__name__)

# Cache TTL
METRICS_CACHE_TTL = 300  # 5 minutos


def get_business_metrics() -> Dict[str, Any]:
    """
    Calcula métricas de negocio actuales.

    Returns:
        dict con todas las métricas
    """
    from extensions import db
    from models import Organizacion, Usuario, Obra, Presupuesto

    metrics: Dict[str, Any] = {
        'timestamp': datetime.utcnow().isoformat(),
    }

    try:
        # Tenants
        metrics['organizaciones'] = {
            'total': db.session.query(Organizacion).count(),
            'activas': db.session.query(Organizacion).filter_by(activa=True).count(),
        }

        # Distribución por plan
        plan_counts = {}
        for plan in ['prueba', 'estandar', 'premium', 'full_premium']:
            count = db.session.query(Organizacion).filter_by(plan_tipo=plan).count()
            plan_counts[plan] = count
        metrics['organizaciones']['por_plan'] = plan_counts

        # Usuarios
        metrics['usuarios'] = {
            'total': db.session.query(Usuario).count(),
            'activos': db.session.query(Usuario).filter_by(activo=True).count(),
        }

        # Login reciente (últimos 7 días)
        try:
            siete_dias = datetime.utcnow() - timedelta(days=7)
            login_recientes = db.session.query(Usuario).filter(
                Usuario.last_login >= siete_dias
            ).count()
            metrics['usuarios']['activos_7d'] = login_recientes
        except Exception:
            metrics['usuarios']['activos_7d'] = None

        # Obras
        try:
            metrics['obras'] = {
                'total': db.session.query(Obra).count(),
                'en_curso': db.session.query(Obra).filter_by(estado='en_curso').count(),
            }
        except Exception:
            metrics['obras'] = {'error': 'No se pudo calcular'}

        # Presupuestos del mes
        try:
            inicio_mes = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            metrics['presupuestos'] = {
                'total': db.session.query(Presupuesto).count(),
                'mes_actual': db.session.query(Presupuesto).filter(
                    Presupuesto.fecha >= inicio_mes.date()
                ).count(),
            }
        except Exception:
            metrics['presupuestos'] = {'error': 'No se pudo calcular'}

    except Exception as e:
        logger.error(f'Error calculando métricas de negocio: {e}')
        metrics['error'] = 'Error parcial al calcular métricas'

    return metrics


def get_cached_metrics() -> Dict[str, Any]:
    """
    Devuelve métricas con caché en Redis (TTL 5 min).
    Si Redis no está disponible, calcula on-demand.
    """
    try:
        import redis
        import json
        import os

        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        r = redis.from_url(redis_url, decode_responses=True)

        cached = r.get('obyra:business_metrics')
        if cached:
            return json.loads(cached)

        # Calcular y cachear
        metrics = get_business_metrics()
        r.setex('obyra:business_metrics', METRICS_CACHE_TTL, json.dumps(metrics, default=str))
        return metrics
    except Exception as e:
        logger.warning(f'Cache de métricas no disponible: {e}')
        return get_business_metrics()


def format_prometheus(metrics: Dict[str, Any]) -> str:
    """
    Formatea métricas como Prometheus exposition format.
    Útil si agregás Prometheus + Grafana al stack.
    """
    lines = [
        '# HELP obyra_organizaciones_total Total de organizaciones registradas',
        '# TYPE obyra_organizaciones_total gauge',
        f'obyra_organizaciones_total {metrics.get("organizaciones", {}).get("total", 0)}',
        '',
        '# HELP obyra_organizaciones_activas Organizaciones activas',
        '# TYPE obyra_organizaciones_activas gauge',
        f'obyra_organizaciones_activas {metrics.get("organizaciones", {}).get("activas", 0)}',
        '',
        '# HELP obyra_usuarios_total Total de usuarios',
        '# TYPE obyra_usuarios_total gauge',
        f'obyra_usuarios_total {metrics.get("usuarios", {}).get("total", 0)}',
        '',
        '# HELP obyra_usuarios_activos_7d Usuarios con login en últimos 7 días',
        '# TYPE obyra_usuarios_activos_7d gauge',
        f'obyra_usuarios_activos_7d {metrics.get("usuarios", {}).get("activos_7d", 0) or 0}',
        '',
        '# HELP obyra_obras_en_curso Obras en estado en_curso',
        '# TYPE obyra_obras_en_curso gauge',
        f'obyra_obras_en_curso {metrics.get("obras", {}).get("en_curso", 0)}',
        '',
    ]

    # Distribución por plan
    por_plan = metrics.get('organizaciones', {}).get('por_plan', {})
    if por_plan:
        lines.extend([
            '# HELP obyra_organizaciones_por_plan Organizaciones por tipo de plan',
            '# TYPE obyra_organizaciones_por_plan gauge',
        ])
        for plan, count in por_plan.items():
            lines.append(f'obyra_organizaciones_por_plan{{plan="{plan}"}} {count}')

    return '\n'.join(lines) + '\n'


# ============================================================
# FUNCIONES DE DETALLE — listas para mostrar en tablas
# ============================================================

def get_organizaciones_detalle() -> list:
    """Lista detallada de organizaciones con métricas asociadas."""
    from extensions import db
    from sqlalchemy import func

    try:
        from models import Organizacion, Usuario, Obra

        orgs = db.session.query(Organizacion).order_by(Organizacion.id.desc()).all()
        result = []
        ahora = datetime.utcnow()
        for o in orgs:
            try:
                num_users = db.session.query(func.count(Usuario.id)).filter_by(
                    organizacion_id=o.id
                ).scalar() or 0
                num_obras = db.session.query(func.count(Obra.id)).filter_by(
                    organizacion_id=o.id
                ).scalar() or 0
            except Exception:
                num_users = 0
                num_obras = 0

            plan_tipo = getattr(o, 'plan_tipo', None) or 'prueba'

            # Calcular fecha de vencimiento
            fecha_vence = None
            dias_restantes = None
            vencido = False

            if plan_tipo == 'prueba':
                # Plan de prueba: 30 días desde fecha_creacion
                if getattr(o, 'fecha_creacion', None):
                    fecha_vence_dt = o.fecha_creacion + timedelta(days=30)
                    fecha_vence = fecha_vence_dt.isoformat()
                    delta = fecha_vence_dt - ahora
                    dias_restantes = delta.days
                    vencido = delta.total_seconds() < 0
            else:
                # Planes pagos: usar fecha_fin_plan si existe
                if getattr(o, 'fecha_fin_plan', None):
                    fecha_vence = o.fecha_fin_plan.isoformat()
                    delta = o.fecha_fin_plan - ahora
                    dias_restantes = delta.days
                    vencido = delta.total_seconds() < 0

            result.append({
                'id': o.id,
                'nombre': o.nombre,
                'plan_tipo': plan_tipo,
                'activa': getattr(o, 'activa', True),
                'fecha_creacion': o.fecha_creacion.isoformat() if getattr(o, 'fecha_creacion', None) else None,
                'max_usuarios': getattr(o, 'max_usuarios', None),
                'max_obras': getattr(o, 'max_obras', None),
                'num_usuarios': num_users,
                'num_obras': num_obras,
                'fecha_fin_plan': fecha_vence,
                'dias_restantes': dias_restantes,
                'vencido': vencido,
            })
        return result
    except Exception as e:
        logger.error(f'Error obteniendo detalle de organizaciones: {e}')
        return []


def get_usuarios_detalle(limit: int = 100) -> list:
    """Lista detallada de usuarios."""
    from extensions import db

    try:
        from models import Usuario, Organizacion

        usuarios = db.session.query(Usuario).order_by(Usuario.id.desc()).limit(limit).all()
        result = []
        for u in usuarios:
            org_nombre = None
            try:
                if u.organizacion_id:
                    org = db.session.query(Organizacion).get(u.organizacion_id)
                    org_nombre = org.nombre if org else None
            except Exception:
                pass

            result.append({
                'id': u.id,
                'nombre': f"{u.nombre or ''} {u.apellido or ''}".strip(),
                'email': u.email,
                'role': getattr(u, 'role', None),
                'organizacion_id': u.organizacion_id,
                'organizacion_nombre': org_nombre,
                'activo': getattr(u, 'activo', True),
                'is_super_admin': getattr(u, 'is_super_admin', False),
                'last_login': u.last_login.isoformat() if getattr(u, 'last_login', None) else None,
                'fecha_creacion': u.fecha_creacion.isoformat() if getattr(u, 'fecha_creacion', None) else None,
            })
        return result
    except Exception as e:
        logger.error(f'Error obteniendo detalle de usuarios: {e}')
        return []


def get_obras_detalle(limit: int = 100) -> list:
    """Lista detallada de obras."""
    from extensions import db

    try:
        from models import Obra, Organizacion

        obras = db.session.query(Obra).order_by(Obra.id.desc()).limit(limit).all()
        result = []
        for o in obras:
            org_nombre = None
            try:
                if o.organizacion_id:
                    org = db.session.query(Organizacion).get(o.organizacion_id)
                    org_nombre = org.nombre if org else None
            except Exception:
                pass

            result.append({
                'id': o.id,
                'nombre': o.nombre,
                'estado': getattr(o, 'estado', None),
                'organizacion_id': o.organizacion_id,
                'organizacion_nombre': org_nombre,
                'fecha_inicio': o.fecha_inicio.isoformat() if getattr(o, 'fecha_inicio', None) else None,
                'fecha_fin': o.fecha_fin.isoformat() if getattr(o, 'fecha_fin', None) else None,
                'progreso': getattr(o, 'progreso', None),
                'cliente': getattr(o, 'cliente', None) or getattr(o, 'cliente_nombre', None),
            })
        return result
    except Exception as e:
        logger.error(f'Error obteniendo detalle de obras: {e}')
        return []

