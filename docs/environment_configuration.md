# Configuración de entornos para OBYRA

Este apunte resume las variables de entorno críticas, la configuración de proveedores externos y las recomendaciones mínimas para preparar entornos de staging y producción.

## 1. Seguridad y base de datos

| Variable | Uso y valor por defecto | Recomendación staging | Recomendación producción | Notas |
| --- | --- | --- | --- | --- |
| `SECRET_KEY` / `SESSION_SECRET` | Inicializa `app.secret_key`. Si ninguna existe, se utiliza `dev-secret-key-change-me`. | Generar claves aleatorias de ≥32 bytes y guardarlas en un gestor de secretos. | Gestionar en un vault con rotación programada y auditoría. | Consolidar en `SECRET_KEY` y reservar `SESSION_SECRET` sólo para overrides.
| `DATABASE_URL` | Configura SQLAlchemy. El arranque exige prefijo `postgresql` mediante `assert`. | `postgresql+psycopg://obyra:<password>@staging-db:5432/obyra_stg` con SSL obligatorio. | `postgresql+psycopg://obyra:<password>@prod-db:5432/obyra_prod` en clúster administrado con backups automáticos. | Ajustar `pool_size` y workers del WSGI según la capacidad de la base.
| `PYTHONIOENCODING` | Se fuerza a `utf-8` si falta para evitar errores en CLI. | Mantener el valor. | Mantener el valor. | Sin acción adicional.

## 2. Feature flags

| Variable | Comportamiento | Uso recomendado |
| --- | --- | --- |
| `WIZARD_BUDGET_BREAKDOWN_ENABLED` | Activa el nuevo flujo de presupuestos. | Encender primero en staging; documentar responsables de activarlo en producción. |
| `WIZARD_BUDGET_SHADOW_MODE` | Ejecuta lógica en sombra. | Útil en staging para validar sin afectar usuarios. |
| `SHOW_IA_CALCULATOR_BUTTON` | Muestra el acceso a la calculadora IA. | Habilitar cuando haya tokens de OpenAI disponibles. |
| `ENABLE_REPORTS` | Activa reportes basados en Matplotlib/WeasyPrint. | Solo cuando SMTP y almacenamiento estén configurados. |
| `ENABLE_GOOGLE_OAUTH_HELP` | Muestra ayuda en consola si faltan credenciales. | Mantener apagado en producción. |

## 3. Proveedores externos

| Área | Variables | Uso actual | Recomendaciones |
| --- | --- | --- | --- |
| Google OAuth | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | `auth.py` y `main_app.py` registran el proveedor solo si ambas variables existen. | Generar credenciales separadas por entorno y registrar URIs de redirección (`/auth/google/callback`). |
| Mercado Pago | `MP_ACCESS_TOKEN`, `MP_WEBHOOK_PUBLIC_URL` | `app.py` carga ambos valores, loguea la URL y `marketplace_payments.py` valida la presencia del token antes de usar el SDK. | Mantener tokens independientes por entorno. Registrar el webhook oficial `/api/payments/mp/webhook`. Añadir monitoreo de respuestas 200. |
| SMTP | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `FROM_EMAIL` | Leídos directamente al enviar notificaciones. | Centralizar en gestor de secretos. En producción exigir TLS y contraseñas de aplicación. |
| Mapas | `MAPS_PROVIDER`, `MAPS_API_KEY`, `MAPS_USER_AGENT`, `GEOCODE_CACHE_TTL` | Configuran proveedor y caché para geocodificación. | `nominatim` es válido para dev; en producción usar proveedor con SLA (ej. Google Maps) y definir key + UA personalizado. |
| Mercado cambiario | `FX_PROVIDER`, `EXCHANGE_FALLBACK_RATE` | Determinan el origen de la cotización y un valor de respaldo. | Establecer fallback diario en staging/prod y monitorear disponibilidad del proveedor principal. |
| IA (OpenAI) | `OPENAI_API_KEY` | Inicializa la calculadora IA. | Mantener claves aisladas por entorno y con límites de gasto. |
| Marketplace | `PLATFORM_COMMISSION_RATE`, `BASE_URL`, `STORAGE_DIR` | Calcula comisiones, arma enlaces y ubica PDFs/activos. | Revisar valores con negocio y asegurar almacenamiento persistente (S3, discos replicados, etc.). |

## 4. Mercado Pago: pruebas rápidas

- Healthcheck: `GET /api/payments/mp/health` → `{ "ok": true, "webhook": <bool> }`.
- Webhook oficial: `POST /api/payments/mp/webhook`.
- Prueba local (sin exponer secretos):

```bash
curl -sS -X POST http://127.0.0.1:8080/api/payments/mp/webhook \
  -H "Content-Type: application/json" \
  -d '{"type":"payment","data":{"id":"test-id"}}'
```

| Situación | Resultado |
| --- | --- |
| Falta `MP_ACCESS_TOKEN` | Respuesta `503` y log "Mercado Pago access token missing". |
| Evento distinto a `payment` | Respuesta `200 {"status": "ignored"}`. |
| Token válido y evento `payment` | Ejecuta el flujo de actualización de órdenes (requiere sandbox configurado). |

Para desarrollo usar un túnel HTTPS (Ngrok, Cloudflare Tunnel) que exponga `http://127.0.0.1:8080`. Registrar la URL pública en el panel de notificaciones de Mercado Pago y actualizar `MP_WEBHOOK_PUBLIC_URL` con esa ruta.

## 5. Dependencias y auditoría

- Dependencias críticas declaradas en `pyproject.toml`: `flask~=3.1.1`, `flask-sqlalchemy~=3.1.1`, `flask-migrate~=4.0.7`, `sqlalchemy~=2.0.41`, `psycopg[binary]>=3.2,<3.3`, `werkzeug~=3.1.3`, `requests~=2.32.3`, `mercadopago~=2.3.0`, `authlib~=1.6.5`.
- Se eliminaron `email-validator` y `pyjwt` por no contar con importaciones activas.
- `requirements.lock` lista herramientas de desarrollo (ruff, mypy, pytest, etc.). Regenerarlo cuando se cambie tooling.
- Script de auditoría: `./scripts/audit_deps.sh <AAAAMMDD>` genera reportes en `docs/audits/`. Actualmente los archivos `20251016-*.txt` informan que `pip-audit`, `safety` y `deptry` no están instalados en este entorno. Ejecutar el script en un ambiente con Internet para obtener resultados reales y adjuntarlos en la carpeta.
- Recomendación: agregar un job de CI que ejecute `pip check` + `./scripts/audit_deps.sh` y suba los artefactos como evidencia de cada release.

