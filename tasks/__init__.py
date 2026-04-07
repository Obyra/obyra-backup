"""
OBYRA — Celery Tasks Module
============================

Tareas asincrónicas para operaciones pesadas. Estas tareas se ejecutan
en el worker de Celery (ver docker-compose celery-worker), no bloqueando
los workers HTTP de Gunicorn.

Estructura:
- emails.py: envío de emails (Resend API)
- pdfs.py: generación de PDFs (WeasyPrint, ReportLab)
- ia.py: cálculos pesados de IA (OpenAI)
- reports.py: generación de reportes pesados

Uso desde el código:
    from tasks.emails import send_email_async
    send_email_async.delay(to='foo@bar.com', subject='Hola', html='<p>Hola</p>')
"""

# Import all task modules to register them with Celery
from tasks import emails  # noqa: F401
from tasks import pdfs    # noqa: F401
from tasks import ia      # noqa: F401
