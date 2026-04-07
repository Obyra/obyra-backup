# Tareas asincrónicas con Celery

OBYRA usa Celery para ejecutar operaciones pesadas (emails, PDFs, IA) en background, sin bloquear los workers HTTP.

## Tareas disponibles

### Emails (`tasks/emails.py`)

```python
from tasks.emails import send_email_async

# Encolar envío de email (no bloquea)
send_email_async.delay(
    to_email='cliente@ejemplo.com',
    subject='Su presupuesto',
    html_content='<p>Hola</p>',
    attachments=[{'filename': 'presu.pdf', 'content': pdf_bytes}]
)
```

Reintenta hasta 3 veces con 60 segundos entre intentos si Resend falla.

### PDFs (`tasks/pdfs.py`)

```python
from tasks.pdfs import generate_presupuesto_pdf_async

# Generar PDF en background
result = generate_presupuesto_pdf_async.delay(presupuesto_id=123)
# El cliente puede consultar luego: result.get(timeout=30)
```

### IA (`tasks/ia.py`)

```python
from tasks.ia import calcular_etapas_ia_async

# Cálculo IA pesado en background
task = calcular_etapas_ia_async.delay(datos_proyecto)
task_id = task.id  # Para consultar luego
```

## Patrón típico en endpoint

```python
@bp.route('/presupuesto/enviar-email', methods=['POST'])
@login_required
def enviar_email():
    presupuesto_id = request.form.get('id')

    # ANTES (síncrono - bloquea 5-10 segundos):
    # send_email(to, subject, html, pdf)
    # return jsonify({'ok': True})

    # DESPUÉS (asincrónico - responde inmediato):
    send_email_async.delay(
        to_email=cliente.email,
        subject=f'Presupuesto #{pres.numero}',
        html_content=html,
    )
    return jsonify({'ok': True, 'message': 'Email en cola de envío'})
```

## Monitoring

Los workers de Celery loguean a `app_logs:/app/logs`. Para ver el estado:

```bash
docker compose -f docker-compose.prod.yml logs -f celery-worker
```

## Reintentos

Las tareas incluyen reintentos automáticos:
- Emails: 3 reintentos cada 60s
- IA: 2 reintentos cada 30s

## Adopción gradual

No es necesario migrar todo a Celery de golpe. Los endpoints sincrónicos siguen funcionando. Migrá según necesidad:

**Prioridad alta** (usuarios esperan):
- Generación de PDF de presupuesto al enviar por email
- Llamadas a OpenAI (calculadora IA)
- Procesamiento de planos

**Prioridad media:**
- Notificaciones por email no urgentes
- Reportes con muchos datos

**No migrar:**
- Operaciones rápidas (<500ms)
- Operaciones que el usuario debe ver el resultado inmediato
