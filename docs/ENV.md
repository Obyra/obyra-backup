# Inventario de entorno y dependencias

Este documento consolida las variables de entorno realmente usadas por la aplicación OBYRA y resume el estado de las dependencias. El objetivo es que cualquier persona pueda preparar entornos de desarrollo, staging y producción sin revisar todo el código.

## 1. Variables de entorno detectadas

| Variable | Descripción | Uso principal |
| --- | --- | --- |
| `SECRET_KEY` / `SESSION_SECRET` | Clave para firmar sesiones Flask. `SESSION_SECRET` tiene prioridad y cae en `SECRET_KEY`; si ninguna existe la app usa un valor inseguro. | `app.py` configura `app.secret_key` al arrancar.
| `DATABASE_URL` | Cadena SQLAlchemy **obligatoriamente** con prefijo `postgresql`. La app falla con `AssertionError` si apunta a otro motor. | Configuración de base de datos en `app.py` antes de inicializar extensiones.
| `AUTO_CREATE_DB` | Bandera heredada para creación automática sólo en scripts legacy que usen SQLite. No tiene efecto cuando la app valida PostgreSQL. | `app.py`, `app_old.py` e `init_marketplace.py` la consultan antes de invocar `db.create_all()`.
| `WIZARD_BUDGET_BREAKDOWN_ENABLED` | Activa el nuevo desglose del asistente de presupuestos. | `_env_flag` en `app.py` carga el valor en `app.config`.
| `WIZARD_BUDGET_SHADOW_MODE` | Ejecuta el asistente en modo sombra. | `_env_flag` en `app.py`.
| `SHOW_IA_CALCULATOR_BUTTON` | Controla la visibilidad del botón de la calculadora IA. | `_env_flag` en `app.py`.
| `ENABLE_REPORTS` | Habilita la generación de reportes (usa Matplotlib/WeasyPrint). | `_env_flag` en `app.py`.
| `ENABLE_GOOGLE_OAUTH_HELP` | Muestra mensajes de ayuda si faltan credenciales OAuth. | `_env_flag` en `app.py`.
| `MAPS_PROVIDER` | Proveedor de geocodificación (`nominatim` por defecto). | `app.py` y `services/geocoding_service.py`.
| `MAPS_API_KEY` | Clave para proveedores de mapas que lo requieran. | `app.py` / servicios de geocodificación.
| `MAPS_USER_AGENT` | User-Agent utilizado al consultar Nominatim. | `services/geocoding_service.py`.
| `GEOCODE_CACHE_TTL` | Tiempo (segundos) del caché de geocodificación. | `services/geocoding_service.py`.
| `MP_ACCESS_TOKEN` | Token de la cuenta de Mercado Pago (sandbox o prod). | Validado en `marketplace_payments.py` antes de inicializar el SDK.
| `MP_WEBHOOK_PUBLIC_URL` | URL pública registrada en Mercado Pago. Debe apuntar a `/api/payments/mp/webhook`. | `app.py` la loguea al iniciar; `marketplace_payments.py` la usa como `notification_url`.
| `PLATFORM_COMMISSION_RATE` | Comisión del marketplace (decimal). | `commission_utils.py`, `models.py` y cálculos de órdenes.
| `BASE_URL` | Dominio público usado en PDFs y enlaces de órdenes. | `marketplace/services/po_pdf.py`.
| `STORAGE_DIR` | Directorio local para archivos generados del marketplace. | `marketplace/services/po_pdf.py`.
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | Credenciales SMTP para notificaciones. | `marketplace/services/emailer.py`.
| `FROM_EMAIL` | Remitente por defecto de los correos. | `marketplace/services/emailer.py`.
| `OPENAI_API_KEY` | Credencial para la calculadora IA. | `calculadora_ia.py`.
| `FX_PROVIDER` | Fuente del tipo de cambio (`bna` por defecto). | `presupuestos.py`.
| `EXCHANGE_FALLBACK_RATE` | Tasa de cambio alternativa manual. | `presupuestos.py`.
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Credenciales OAuth para login con Google. | `auth.py` y `main_app.py`.
| `PYTHONIOENCODING` | Se fuerza a `utf-8` si no existe para evitar errores en CLI. | `_ensure_utf8_io()` en `app.py`.

> **Checklist previo a cada despliegue**
> - Secretos (`SECRET_KEY`, `SESSION_SECRET`, `MP_ACCESS_TOKEN`, `SMTP_PASSWORD`, `OPENAI_API_KEY`, `GOOGLE_OAUTH_*`) cargados en el gestor de secretos del entorno.
> - `DATABASE_URL` apunta a PostgreSQL administrado con TLS y backups.
> - `MP_WEBHOOK_PUBLIC_URL` responde `200` desde Internet y coincide con la ruta `/api/payments/mp/webhook`.
> - `BASE_URL` / `STORAGE_DIR` configurados según dominio y almacenamiento persistente.
> - Feature flags (`ENABLE_REPORTS`, `WIZARD_*`, `SHOW_IA_CALCULATOR_BUTTON`) documentados con su estado actual.

## 2. Configuración mínima por entorno

| Variable | Desarrollo local | Staging | Producción |
| --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://obyra:password@localhost:5435/obyra_dev` | `postgresql+psycopg://obyra:<password>@staging-db:5432/obyra_stg` | `postgresql+psycopg://obyra:<password>@prod-db:5432/obyra_prod` |
| `SECRET_KEY` / `SESSION_SECRET` | Valores simples pero únicos en `.env`. | Generados en un gestor de secretos por entorno. | Claves de alta entropía con rotación programada. |
| `MP_ACCESS_TOKEN` | Token sandbox. | Token de la cuenta staging. | Token productivo (vault). |
| `MP_WEBHOOK_PUBLIC_URL` | URL pública del túnel apuntando a `/api/payments/mp/webhook`. | `https://staging.tu-dominio.com/api/payments/mp/webhook`. | `https://app.tu-dominio.com/api/payments/mp/webhook`. |
| `BASE_URL` | `http://127.0.0.1:8080` (o dominio expuesto por el túnel). | Dominio staging. | Dominio público oficial. |
| `SMTP_*` | Mailhog o servidor local. | Cuenta transaccional sandbox. | Proveedor transaccional con TLS. |
| `OPENAI_API_KEY` | Key de pruebas con límites. | Key aislada de staging. | Key productiva bajo controles de coste. |
| `MAPS_PROVIDER` / `MAPS_API_KEY` | `nominatim` o proveedor alternativo de pruebas. | Proveedor contratado con key restringida. | Proveedor con SLA y límites configurados. |
| `PLATFORM_COMMISSION_RATE` | `0.02` (default). | Ajustado al escenario de pruebas. | Porcentaje oficial del marketplace. |
| `FX_PROVIDER` / `EXCHANGE_FALLBACK_RATE` | `bna` + fallback opcional. | Igual a producción (validar monitoreo). | Según política financiera. |

> Nota: usa `postgresql+psycopg://` en todos los entornos. El contenedor local recomendado es `obyra-pg-stg` en el puerto `5435`. Agrega `?sslmode=require` si el proveedor administrado de PostgreSQL lo exige.

## 3. Mercado Pago: pruebas y verificación

- La app loguea al inicio `MP webhook URL: ...` si la variable está presente y muestra un warning si falta.
- Endpoint de health: `GET /api/payments/mp/health` devuelve `{"ok": true, "webhook": <bool>}`.
- Webhook oficial: `POST /api/payments/mp/webhook`.
- Prueba rápida local:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/payments/mp/webhook \
  -H "Content-Type: application/json" \
  -d '{"type":"payment","data":{"id":"test-id"}}'
```

| Escenario | Respuesta esperada |
| --- | --- |
| Falta `MP_ACCESS_TOKEN` | `503` con `{ "error": "Mercado Pago no está configurado" }` y log de error. |
| Evento que no es `payment` | `200` con `{ "status": "ignored" }`. |
| Evento `payment` válido | Flujo completo de actualización de orden (requiere token y SDK configurado). |

## 4. Estado de dependencias

- Se actualizaron los rangos críticos para alinearse con el stack actual: `authlib~=1.6.5`, `flask~=3.1.1`, `flask-sqlalchemy~=3.1.1`, `flask-migrate~=4.0.7`, `sqlalchemy~=2.0.41`, `psycopg[binary]>=3.2,<3.3`, `werkzeug~=3.1.3`, `requests~=2.32.3`, `mercadopago~=2.3.0`.
- Bibliotecas no utilizadas identificadas y removidas del `pyproject.toml`: `email-validator` y `pyjwt` (no existen importaciones activas).
- Dependencias pesadas (`matplotlib`, `weasyprint`, `openai`) siguen presentes porque respaldan funcionalidades disponibles bajo flags. Evaluar moverlas a extras opcionales cuando se delimite su uso.
- Existe `requirements.lock` con herramientas de desarrollo (black, isort, ruff, etc.). Regenerar este archivo si se cambian versiones o se añade tooling nuevo.

## 5. Auditoría periódica

| Comando | Propósito | Salida actual |
| --- | --- | --- |
| `./scripts/audit_deps.sh` | Ejecuta `pip-audit`, `safety check` y `deptry .`, guardando reportes en `docs/audits/AAAAMMDD-*.txt`. | En este entorno de CI los binarios no están instalados, por lo que los reportes de `20251016-*` registran `[missing] …`. |
| `pip check` | Verifica conflictos de versiones instaladas. | Ejecutar tras instalar dependencias reales. |

> **Siguiente paso recomendado:** configurar un job de CI que instale las dependencias de producción y ejecute `./scripts/audit_deps.sh` junto con `pip check`. De esta forma se almacenarán reportes reales en `docs/audits/` y se evitarán regresiones de seguridad.

