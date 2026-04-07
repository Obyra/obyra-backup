"""
Tareas Celery para operaciones pesadas de IA.

Las llamadas a OpenAI pueden tardar 10-30 segundos. Procesar
en background evita timeouts en el frontend.
"""

import logging
from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name='tasks.ia.calcular_etapas_ia_async', bind=True, max_retries=2)
def calcular_etapas_ia_async(self, datos_proyecto):
    """
    Ejecuta el cálculo IA de etapas en background.

    Args:
        datos_proyecto: Diccionario con superficie, tipo_obra, etc

    Returns:
        dict con resultado del cálculo o error
    """
    try:
        from app import app
        with app.app_context():
            from calculadora_ia import calcular_etapas_seleccionadas
            resultado = calcular_etapas_seleccionadas(datos_proyecto)
            return {'ok': True, 'resultado': resultado}
    except Exception as exc:
        logger.error(f'[TASK calcular_etapas_ia_async] Error: {exc}')
        try:
            raise self.retry(countdown=30, exc=exc)
        except self.MaxRetriesExceededError:
            return {'ok': False, 'error': 'Error al calcular etapas con IA'}


@celery.task(name='tasks.ia.analizar_plano_async', bind=True, max_retries=2)
def analizar_plano_async(self, plano_path, contexto):
    """
    Analiza un plano con IA en background.

    Args:
        plano_path: Path del archivo del plano
        contexto: Contexto adicional del proyecto

    Returns:
        dict con análisis o error
    """
    try:
        from app import app
        with app.app_context():
            from calculadora_ia import analizar_plano_con_ia
            resultado = analizar_plano_con_ia(plano_path, contexto)
            return {'ok': True, 'analisis': resultado}
    except Exception as exc:
        logger.error(f'[TASK analizar_plano_async] Error: {exc}')
        try:
            raise self.retry(countdown=60, exc=exc)
        except self.MaxRetriesExceededError:
            return {'ok': False, 'error': 'Error al analizar plano'}
