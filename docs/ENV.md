# Guía de variables de entorno y dependencias

## Inventario de variables utilizadas

| Variable | Descripción y consideraciones | Uso en código |
| --- | --- | --- |
| `SESSION_SECRET` / `SECRET_KEY` | Clave para firmar cookies Flask. Definir valores distintos y rotar en cada entorno. | `app.py` inicializa `app.secret_key` priorizando `SESSION_SECRET` y `SECRET_KEY`. 【F:app.py†L96-L100】 |
| `DATABASE_URL` | URL de conexión SQLAlchemy. Debe apuntar a PostgreSQL administrado en todos los entornos. | Validada al arrancar la app con un `assert` que exige prefijo `postgresql`. 【F:app.py†L120-L142】 |
| `AUTO_CREATE_DB` | Permite crear esquema automáticamente cuando se usa SQLite local. Mantener desactivado en Postgres. | El helper `maybe_create_sqlite_schema` sólo actúa con SQLite y flag `"1"`. 【F:app.py†L1054-L1062】 |
| `WIZARD_BUDGET_BREAKDOWN_ENABLED` | Activa el nuevo desglose del wizard de presupuestos. | Flag leída mediante `_env_flag`. 【F:app.py†L168-L175】 |
| `WIZARD_BUDGET_SHADOW_MODE` | Ejecuta el wizard en modo sombra para pruebas. | `_env_flag` en configuración de Flask. 【F:app.py†L172-L175】 |
| `SHOW_IA_CALCULATOR_BUTTON` | Muestra u oculta acceso a la calculadora IA. | `_env_flag` guardado en `app.config`. 【F:app.py†L177-L178】 |
| `ENABLE_REPORTS` | Habilita servicio de reportes avanzados. | `_env_flag` con nombre `ENABLE_REPORTS`. 【F:app.py†L177-L178】 |
| `MAPS_PROVIDER` | Selecciona proveedor de geocodificación (`nominatim` por defecto). | Cargado en `app.config`. 【F:app.py†L179-L180】 |
| `MAPS_API_KEY` | API key para proveedores que lo requieran. | Guardado en `app.config` y usado por `services.geocoding_service`. 【F:app.py†L179-L180】【F:services/geocoding_service.py†L112-L119】 |
| `MAPS_USER_AGENT` | User-Agent personalizado para consultas Nominatim. | Constante `DEFAULT_USER_AGENT`. 【F:services/geocoding_service.py†L18-L70】 |
| `GEOCODE_CACHE_TTL` | TTL del caché de geocodificación (segundos). | Valor `CACHE_TTL_SECONDS`. 【F:services/geocoding_service.py†L18-L58】 |
| `MP_ACCESS_TOKEN` | Token Mercado Pago. Requerido para preferencias y webhooks. | Cargado en `app.config` y validado en endpoints. 【F:app.py†L181-L196】【F:marketplace_payments.py†L25-L116】 |
| `MP_WEBHOOK_PUBLIC_URL` | URL pública registrada en Mercado Pago que debe apuntar a `/api/payments/mp/webhook`. | Guardada en configuración, logueada al inicio y usada en webhooks. 【F:app.py†L181-L196】【F:marketplace_payments.py†L65-L190】 |
| `BASE_URL` | URL base pública usada en enlaces y PDFs (debe coincidir con host y puerto expuestos). | Consumida en generación de preferencias y PDFs. 【F:marketplace_payments.py†L58-L66】【F:marketplace/services/po_pdf.py†L200-L217】 |
| `STORAGE_DIR` | Directorio raíz persistente para archivos de marketplace. | Utilizado al generar PDFs. 【F:marketplace/services/po_pdf.py†L52-L60】 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | Credenciales SMTP para notificaciones marketplace. | Leídas al enviar emails. 【F:marketplace/services/emailer.py†L28-L77】 |
| `FROM_EMAIL` | Remitente de correos marketplace. | Default configurable en emailer. 【F:marketplace/services/emailer.py†L28-L35】 |
| `OPENAI_API_KEY` | Token para la calculadora IA. Mantener en secreto y rotar según políticas de OpenAI. | Usado al instanciar cliente `OpenAI`. 【F:calculadora_ia.py†L15-L24】 |
| `PLATFORM_COMMISSION_RATE` | Porcentaje de comisión del marketplace. | Usado en modelos y utilidades de comisiones. 【F:models.py†L2447-L2451】【F:commission_utils.py†L9-L113】 |
| `FX_PROVIDER` | Proveedor de tipo de cambio (actualmente `bna`). | Controla fetch de cotizaciones. 【F:presupuestos.py†L151-L185】 |
| `EXCHANGE_FALLBACK_RATE` | Tasa de cambio fallback manual. | Convertida a `Decimal` si existe. 【F:presupuestos.py†L155-L183】 |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Credenciales OAuth para login con Google. | Registradas por Authlib cuando están disponibles. 【F:auth.py†L108-L133】【F:main_app.py†L17-L50】 |
| `ENABLE_GOOGLE_OAUTH_HELP` | Muestra instrucciones de configuración en consola cuando faltan credenciales. | Flag evaluada en `auth.py`. 【F:auth.py†L118-L131】 |
| `PYTHONIOENCODING` | Garantiza IO en UTF-8 cuando se ejecutan comandos CLI. | Se establece automáticamente si falta. 【F:app.py†L39-L90】 |

## Valores sugeridos por entorno

| Variable | Desarrollo | Staging | Producción |
| --- | --- | --- | --- |
| `DATABASE_URL` | `sqlite:///tmp/dev.db` (o Postgres local) | `postgresql+psycopg://obyra:<password>@staging-db:5432/obyra_stg` | `postgresql+psycopg://obyra:<password>@prod-db:5432/obyra_prod` |
| `SECRET_KEY` / `SESSION_SECRET` | Claves simples pero únicas en `.env` local. | Claves aleatorias generadas por el gestor de secretos de la plataforma. | Claves de alta entropía rotadas periódicamente. |
| `MP_ACCESS_TOKEN` | Token de sandbox de Mercado Pago. | Token de la cuenta staging. | Token productivo validado y almacenado en vault. |
| `MP_WEBHOOK_PUBLIC_URL` | URL de túnel (ej. `https://subdominio.ngrok.app/api/payments/mp/webhook`). | `https://staging.tu-dominio.com/api/payments/mp/webhook` | `https://app.tu-dominio.com/api/payments/mp/webhook` |
| `BASE_URL` | `http://localhost:5000` (expuesto a través de túnel para probar webhooks). | `https://staging.tu-dominio.com` | `https://app.tu-dominio.com` |
| `MAPS_PROVIDER` / `MAPS_API_KEY` | `nominatim` sin key o provider alternativo (`google`) con key de pruebas. | Provider alineado con contratos (ej. Google Maps) con key restringida por IP. | Key productiva con cuotas y facturación controladas. |
| `SMTP_*` | SMTP local o Mailhog. | Cuenta transaccional sandbox. | Proveedor transaccional con DKIM/SPF configurados. |
| `OPENAI_API_KEY` | Key de pruebas con cuotas limitadas. | Key de proyecto staging (aislada del prod). | Key productiva bajo budget guardrails. |
| `PLATFORM_COMMISSION_RATE` | `0.02` por defecto. | Ajustar al porcentaje vigente en staging. | Porcentaje oficial del marketplace. |
| `FX_PROVIDER` / `EXCHANGE_FALLBACK_RATE` | `bna` + fallback manual opcional. | Igual a producción, revisar monitoreo. | `bna` y fallback según política financiera. |
| `GOOGLE_OAUTH_*` | Credenciales OAuth en consola Google para entorno dev (redirect via túnel). | Proyecto Google Cloud exclusivo de staging. | Proyecto Google Cloud productivo con dominios verificados. |
| `STORAGE_DIR` | `./storage` dentro del repo. | Volumen persistente montado (ej. `/var/lib/obyra/storage`). | Bucket o volumen replicado (S3, GCS, etc.). |

### Uso de túneles para Mercado Pago en desarrollo

1. Iniciar la aplicación local (`flask run` o `python app.py`).
2. Crear un túnel HTTPS estable (Ngrok, Cloudflare Tunnel) que apunte a `http://127.0.0.1:5000`.
3. Exportar `MP_WEBHOOK_PUBLIC_URL` con la URL pública del túnel (`https://<subdominio>.ngrok.app/api/payments/mp/webhook`).
4. Configurar la misma URL en el panel de notificaciones de Mercado Pago (modo sandbox).
5. Mantener el túnel abierto mientras se ejecutan pruebas de checkout.

### Pruebas locales del webhook

```bash
curl -sS -X POST http://127.0.0.1:8080/api/payments/mp/webhook \
  -H "Content-Type: application/json" \
  -d '{"type":"payment","data":{"id":"test-id"}}'
```

- Si falta `MP_ACCESS_TOKEN`, la respuesta será `503` con mensaje "Mercado Pago no está configurado".
- Para notificaciones que no sean de tipo `payment`, el webhook responde `200 {"status": "ignored"}`.
- Existe un healthcheck de apoyo en `GET /api/payments/mp/health` que devuelve `{ "ok": true, "webhook": <bool> }` para validar despliegues.

### Checklist previo a despliegues

- [ ] Secretos (`SECRET_KEY`, `SESSION_SECRET`, `OPENAI_API_KEY`, `MP_ACCESS_TOKEN`, `SMTP_PASSWORD`, `GOOGLE_OAUTH_*`) cargados en el gestor de secretos de la plataforma.
- [ ] `DATABASE_URL` apunta a PostgreSQL administrado con TLS obligatorio y backups automáticos.
- [ ] Revisar `PLATFORM_COMMISSION_RATE` y límites de `FX_PROVIDER` contra políticas financieras.
- [ ] Validar `BASE_URL`, `STORAGE_DIR` y credenciales SMTP según dominio del entorno.
- [ ] Confirmar que `MAPS_PROVIDER` y `MAPS_API_KEY` corresponden al proveedor contratado.
- [ ] Verificar que los webhooks (`MP_WEBHOOK_PUBLIC_URL`) respondan 200 OK desde la URL pública.
- [ ] Ejecutar script de auditoría de dependencias antes de cada release (`scripts/audit_deps.sh`).

## Dependencias: hallazgos y recomendaciones

- Se reemplazó `psycopg2-binary` por `psycopg[binary]` y se ajustaron los rangos de versiones críticas (Flask 3.1, SQLAlchemy 2.0.41, Alembic vía `flask-migrate` 4.0.7) para alinearse con el soporte actual de los mantenedores. 【F:pyproject.toml†L1-L24】
- Se eliminó `flask-dance` y `oauthlib` del listado principal al no existir importaciones activas en el código. 【F:pyproject.toml†L1-L24】
- Mantener bibliotecas pesadas (`matplotlib`, `weasyprint`, `openai`) sólo en despliegues que necesiten dichas capacidades; evaluar moverlas a extras en futuros PRs.

### Auditorías automatizadas

Se añadió el script `scripts/audit_deps.sh` para ejecutar `pip-audit`, `safety` y `deptry`, guardando reportes en `docs/audits/`. Ver sección siguiente para los resultados del intento en este entorno.

