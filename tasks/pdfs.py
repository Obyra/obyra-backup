"""
Tareas Celery para generación de PDFs.

Las generaciones de PDF (presupuestos, recibos, reportes) son operaciones
pesadas que pueden bloquear workers HTTP por varios segundos.
"""

import logging
from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name='tasks.pdfs.generate_presupuesto_pdf_async', bind=True)
def generate_presupuesto_pdf_async(self, presupuesto_id):
    """
    Genera PDF de presupuesto en background y lo guarda en storage.

    Args:
        presupuesto_id: ID del presupuesto

    Returns:
        dict con 'ok' y 'path' del PDF generado
    """
    try:
        from app import app
        with app.app_context():
            from models import Presupuesto
            from blueprint_presupuestos.pdf_email import _generar_pdf_presupuesto

            pres = Presupuesto.query.get(presupuesto_id)
            if not pres:
                return {'ok': False, 'error': 'Presupuesto no encontrado'}

            pdf_bytes = _generar_pdf_presupuesto(pres)

            # Guardar en storage
            import os
            storage_dir = os.path.join('storage', 'pdfs', 'presupuestos')
            os.makedirs(storage_dir, exist_ok=True)
            pdf_path = os.path.join(storage_dir, f'presupuesto_{presupuesto_id}.pdf')

            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)

            return {'ok': True, 'path': pdf_path}
    except Exception as exc:
        logger.error(f'[TASK generate_presupuesto_pdf_async] Error: {exc}')
        return {'ok': False, 'error': 'Error al generar PDF'}


@celery.task(name='tasks.pdfs.generate_reporte_pdf_async', bind=True)
def generate_reporte_pdf_async(self, reporte_tipo, params):
    """
    Genera PDF de reporte en background.

    Args:
        reporte_tipo: 'obras', 'costos', 'inventario', 'liquidacion_mo'
        params: Parámetros del reporte (org_id, fecha_desde, fecha_hasta, etc)

    Returns:
        dict con 'ok' y 'path' del PDF
    """
    try:
        from app import app
        with app.app_context():
            # Delegar al servicio correspondiente
            from reports_service import generate_pdf_report
            pdf_path = generate_pdf_report(reporte_tipo, params)
            return {'ok': True, 'path': pdf_path}
    except Exception as exc:
        logger.error(f'[TASK generate_reporte_pdf_async] Error: {exc}')
        return {'ok': False, 'error': 'Error al generar reporte'}
