"""
Tareas Celery para envío de emails.

Envía emails de forma asincrónica para no bloquear workers HTTP.
"""

import logging
from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name='tasks.emails.send_email_async', bind=True, max_retries=3)
def send_email_async(self, to_email, subject, html_content,
                     attachments=None, reply_to=None, text_content=None):
    """
    Envía email de forma asincrónica usando Resend API.

    Args:
        to_email: Email destinatario
        subject: Asunto
        html_content: Contenido HTML
        attachments: Lista de adjuntos opcional
        reply_to: Email para respuestas
        text_content: Versión texto plano

    Returns:
        bool: True si se envió, False si falló
    """
    try:
        from services.email_service import send_email
        result = send_email(
            to_email=to_email,
            subject=subject,
            html_content=html_content,
            attachments=attachments,
            reply_to=reply_to,
            text_content=text_content,
        )
        if not result:
            # Reintentar si falló (Resend caído, rate limit, etc)
            raise self.retry(countdown=60, exc=Exception('Email send failed'))
        return result
    except Exception as exc:
        logger.error(f'[TASK send_email_async] Error: {exc}')
        try:
            raise self.retry(countdown=60, exc=exc)
        except self.MaxRetriesExceededError:
            logger.error(f'[TASK send_email_async] Max retries exceeded for {to_email}')
            return False


@celery.task(name='tasks.emails.send_bulk_emails_async')
def send_bulk_emails_async(emails_list):
    """
    Envía múltiples emails en lote.

    Args:
        emails_list: Lista de dicts con keys: to_email, subject, html_content, [attachments]
    """
    results = []
    for email_data in emails_list:
        result = send_email_async.delay(**email_data)
        results.append(result.id)
    return results
