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
