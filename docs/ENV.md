# Inventario de entorno y dependencias

Este documento consolida las variables de entorno realmente usadas por la aplicación OBYRA y resume el estado de las dependencias. El objetivo es que cualquier persona pueda preparar entornos de desarrollo, staging y producción sin revisar todo el código.

---

## 1. Variables de entorno detectadas

| Variable | Descripción | Uso principal |
|---|---|---|
| `SECRET_KEY` / `SESSION_SECRET` | Clave para firmar sesiones Flask. `SESSION_SECRET` tiene prioridad y cae en `SECRET_KEY`; si ninguna existe la app usa un valor inseguro. | `app.py` configura `app.secret_key` al arrancar. |
| `DATABASE_URL` | Cadena SQLAlchemy **obligatoriamente** con prefijo `postgresql`. La app falla si apunta a otro motor (salvo tests). | Config DB en `app.py` antes de inicializar extensiones. |
| `AUTO_CREATE_DB` | Bandera heredada para auto-crear schema solo cuando la URI es SQLite (dev/scripts). | Varios scripts legacy; noop en Postgres. |
| `WIZARD_BUDGET_BREAKDOWN_ENABLED` | Activa el nuevo desglose del asistente de presupuestos. | `_env_flag` en `app.py`. |
| `WIZARD_BUDGET_SHADOW_MODE` | Ejecuta el asistente en modo sombra. | `_env_flag` en `app.py`. |
| `SHOW_IA_CALCULATOR_BUTTON` | Muestra/oculta botón de calculadora IA. | `_env_flag` en `app.py`. |
| `ENABLE_REPORTS` | Habilita reportes (Matplotlib/WeasyPrint). | `_env_flag` en `app.py`. |
| `ENABLE_GOOGLE_OAUTH_HELP` | Mensajes de ayuda para configurar OAuth. | `_env_flag` en `app.py`. |
| `MAPS_PROVIDER` | Proveedor de geocodificación (`nominatim` por defecto). | `app.py` y servicios de geocoding. |
| `MAPS_API_KEY` | API key para mapas (si el proveedor lo requiere). | `app.py`/servicios. |
| `MAPS_USER_AGENT` | User-Agent para Nominatim. | `services/geocoding_service.py`. |
| `GEOCODE_CACHE_TTL` | TTL de caché de geocodificación (seg). | `services/geocoding_service.py`. |
| `MP_ACCESS_TOKEN` | Token de Mercado Pago (sandbox/prod). | Inicialización/SDK de MP. |
| `MP_WEBHOOK_PUBLIC_URL` | URL pública registrada en MP → **debe apuntar a** `/api/payments/mp/webhook`. | `app.py` la loguea; usada como `notification_url`. |
| `PLATFORM_COMMISSION_RATE` | Comisión del marketplace (decimal). | `commission_utils.py`, `models.py`. |
| `BASE_URL` | Dominio público usado en PDFs/enlaces. | `marketplace/services/po_pdf.py`. |
| `STORAGE_DIR` | Directorio local para archivos generados. | `marketplace/services/po_pdf.py`. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | SMTP para notificaciones. | `marketplace/services/emailer.py`. |
| `FROM_EMAIL` | Remitente por defecto. | `marketplace/services/emailer.py`. |
| `OPENAI_API_KEY` | Credencial para calculadora IA. | `calculadora_ia.py`. |
| `FX_PROVIDER` | Fuente del tipo de cambio (`bna` por defecto). | `presupuestos.py`. |
| `EXCHANGE_FALLBACK_RATE` | Tasa de cambio alternativa manual. | `presupuestos.py`. |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | OAuth para login con Google. | `auth.py`. |
| `PYTHONIOENCODING` | Forzada a `utf-8` para evitar errores en CLI. | `_ensure_utf8_io()` en `app.py`. |

> **Checklist antes de desplegar**
> - Secretos (`SECRET_KEY`, `SESSION_SECRET`, `MP_ACCESS_TOKEN`, `SMTP_PASSWORD`, `OPENAI_API_KEY`, `GOOGLE_OAUTH_*`) en el gestor de secretos del entorno.
> - `DATABASE_URL` → PostgreSQL administrado con TLS/backups (si es Neon, `sslmode=require`).
> - `MP_WEBHOOK_PUBLIC_URL` responde `200` y apunta a `/api/payments/mp/webhook`.
> - `BASE_URL` / `STORAGE_DIR` configurados según dominio y storage.
> - Feature flags (`ENABLE_REPORTS`, `WIZARD_*`, `SHOW_IA_CALCULATOR_BUTTON`) documentados con su estado.

---

## 2. Configuración mínima por entorno

| Variable | Desarrollo local | Staging | Producción |
|---|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://obyra:password@localhost:5433/obyra_dev` | `postgresql+psycopg://obyra:<password>@staging-db:5432/obyra_stg` | `postgresql+psycopg://obyra:<password>@prod-db:5432/obyra_prod` |
| `SECRET_KEY` / `SESSION_SECRET` | Valores simples pero únicos en `.env`. | En gestor de secretos por entorno. | Claves de alta entropía con rotación. |
| `MP_ACCESS_TOKEN` | Token sandbox. | Token staging. | Token productivo (vault). |
| `MP_WEBHOOK_PUBLIC_URL` | Túnel público → `/api/payments/mp/webhook`. | `https://staging.tu-dominio.com/api/payments/mp/webhook` | `https://app.tu-dominio.com/api/payments/mp/webhook` |
| `BASE_URL` | `http://127.0.0.1:8080` (o dominio del túnel). | Dominio staging. | Dominio público oficial. |
| `SMTP_*` | Mailhog/Mailtrap. | Cuenta transaccional sandbox. | Proveedor transaccional con TLS. |
| `OPENAI_API_KEY` | Key de pruebas. | Key aislada de staging. | Key productiva con límites. |
| `MAPS_PROVIDER` / `MAPS_API_KEY` | `nominatim` o proveedor de pruebas. | Proveedor con key restringida. | Proveedor con SLA/quotas. |
| `PLATFORM_COMMISSION_RATE` | `0.02`. | Según pruebas. | % oficial. |
| `FX_PROVIDER` / `EXCHANGE_FALLBACK_RATE` | `bna` + fallback opcional. | Igual a prod. | Política financiera. |

---

## 3. Mercado Pago: pruebas y verificación

- La app loguea al inicio `MP webhook URL: ...` si la variable está presente y muestra *warning* si falta.
- Webhook oficial: `POST /api/payments/mp/webhook`.
- Prueba rápida local:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/payments/mp/webhook \
  -H "Content-Type: application/json" \
  -d '{"type":"payment","data":{"id":"test-id"}}'
