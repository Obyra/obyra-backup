# Inventario de entorno y dependencias

Este documento consolida las variables de entorno realmente usadas por la aplicación OBYRA y resume el estado de las dependencias. El objetivo es que cualquier persona pueda preparar entornos de **desarrollo**, **staging** y **producción** sin revisar todo el código.

---

## 1) Variables de entorno detectadas

| Variable | Descripción | Uso principal |
|---|---|---|
| `SECRET_KEY` / `SESSION_SECRET` | Clave para firmar sesiones Flask. **`SESSION_SECRET` tiene prioridad** y cae en `SECRET_KEY`. Si ninguna existe, la app usa un valor inseguro (solo válido en dev). | `app.py` → `app.secret_key` |
| `DATABASE_URL` | Cadena SQLAlchemy. **Producción/Staging: PostgreSQL (psycopg)**. En **tests** puede usarse `sqlite:///:memory:`. Si el host es **Neon**, se fuerza `sslmode=require` si faltara. | Config DB en `app.py` antes de inicializar extensiones |
| `AUTO_CREATE_DB` | Solo crea schema si la URI es **SQLite** (útil para scripts locales/legacy). No aplica a Postgres. | Helper `maybe_create_sqlite_schema()` |
| `SHOW_IA_CALCULATOR_BUTTON` | Muestra/oculta el botón de calculadora IA. | `_env_flag` en `app.py` |
| `ENABLE_REPORTS` | Habilita módulo de reportes (Matplotlib/WeasyPrint). | `_env_flag` en `app.py` |
| `ENABLE_GOOGLE_OAUTH_HELP` | Mensajes de ayuda si faltan credenciales OAuth. | `_env_flag` en `app.py` |
| `WIZARD_BUDGET_BREAKDOWN_ENABLED` | Activa el nuevo desglose del asistente de presupuestos. | `_env_flag` en `app.py` |
| `WIZARD_BUDGET_SHADOW_MODE` | Ejecuta el asistente en “modo sombra”. | `_env_flag` en `app.py` |
| `MAPS_PROVIDER` | Proveedor de geocodificación (`nominatim` por defecto). | `app.py` y `services/geocoding_service.py` |
| `MAPS_API_KEY` | API key para mapas (si el proveedor lo requiere). | `app.py` / servicios |
| `MAPS_USER_AGENT` | User-Agent para Nominatim. | `services/geocoding_service.py` |
| `GEOCODE_CACHE_TTL` | TTL (segundos) del caché de geocodificación. | `services/geocoding_service.py` |
| `MP_ACCESS_TOKEN` | Token de Mercado Pago (sandbox/prod). | Inicialización/SDK MP y validaciones en arranque |
| `MP_WEBHOOK_PUBLIC_URL` | URL pública registrada en MP. **Debe apuntar a** `/api/payments/mp/webhook`. | Log de arranque en `app.py` y `notification_url` |
| `PLATFORM_COMMISSION_RATE` | Comisión del marketplace (decimal). | `commission_utils.py`, `models.py`, órdenes |
| `BASE_URL` | Dominio público usado en PDFs y enlaces. | `marketplace/services/po_pdf.py` |
| `STORAGE_DIR` | Directorio local para archivos generados. | `marketplace/services/po_pdf.py` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | SMTP para notificaciones. | `marketplace/services/emailer.py` |
| `FROM_EMAIL` | Remitente por defecto. | `marketplace/services/emailer.py` |
| `OPENAI_API_KEY` | Credencial para calculadora IA. | `calculadora_ia.py` |
| `FX_PROVIDER` | Fuente del tipo de cambio (`bna` por defecto). | `services/exchange/*`, `presupuestos.py` |
| `EXCHANGE_FALLBACK_RATE` | Tasa de cambio alternativa manual. | `services/exchange/*` |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | OAuth para login con Google. | `auth.py` |
| `PYTHONIOENCODING` | Forzada a `utf-8` si no existe, para evitar errores en CLI. | `_ensure_utf8_io()` en `app.py` |

> **Checklist previo a cada despliegue**
> - Secretos (`SESSION_SECRET/SECRET_KEY`, `MP_ACCESS_TOKEN`, `SMTP_PASSWORD`, `OPENAI_API_KEY`, `GOOGLE_OAUTH_*`) cargados en el gestor de secretos del entorno.
> - `DATABASE_URL` → **PostgreSQL** administrado con TLS/backups (si es **Neon**, verificar `sslmode=require`).
> - `MP_WEBHOOK_PUBLIC_URL` responde `200` desde Internet y coincide con `/api/payments/mp/webhook`.
> - `BASE_URL` / `STORAGE_DIR` configurados según dominio y almacenamiento persistente.
> - Feature flags (`ENABLE_REPORTS`, `WIZARD_*`, `SHOW_IA_CALCULATOR_BUTTON`) documentados con su estado actual.

---

## 2) Configuración mínima por entorno

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
| `PLATFORM_COMMISSION_RATE` | `0.02` (default). | Según pruebas. | % oficial. |
| `FX_PROVIDER` / `EXCHANGE_FALLBACK_RATE` | `bna` + fallback opcional. | Igual a prod. | Política financiera. |

---

## 3) Mercado Pago: pruebas y verificación

- La app loguea al inicio `MP webhook URL: ...` si la variable está presente y muestra **warning** si falta.
- **Webhook oficial:** `POST /api/payments/mp/webhook`.
- **Health** (si está expuesto): `GET /api/payments/mp/health` → `{"ok": true, "webhook": <bool>}`.

**Prueba rápida local**
```bash
curl -sS -X POST http://127.0.0.1:8080/api/payments/mp/webhook \
  -H "Content-Type: application/json" \
  -d '{"type":"payment","data":{"id":"test-id"}}'
4) Estado de dependencias

Versionado alineado con el stack actual:
authlib~=1.6.5, flask~=3.1.1, flask-sqlalchemy~=3.1.1, flask-migrate~=4.0.7,
sqlalchemy~=2.0.41, psycopg[binary]>=3.2,<3.3, werkzeug~=3.1.3,
requests~=2.32.3, mercadopago~=2.3.0.

Bibliotecas pesadas presentes por flags: matplotlib, weasyprint, openai. Evaluar mover a extras cuando se delimite su uso.

Librerías sin uso (removidas): email-validator, pyjwt (no hay importaciones activas).

Existe requirements.lock con tooling (black, isort, ruff, etc.). Regenerar al cambiar versiones o herramientas.
5) Auditoría periódica
Comando	Propósito	Nota
./scripts/audit_deps.sh	Corre pip-audit, safety check y deptry ., guardando reportes en docs/audits/AAAAMMDD-*.txt.	Configurar en CI para instalar deps reales y almacenar reportes.
pip check	Verifica conflictos de versiones instaladas.	Ejecutar tras pip install -r requirements.txt.

Siguiente paso recomendado: agregar un job de CI que instale las dependencias de producción y ejecute ./scripts/audit_deps.sh + pip check, de modo que docs/audits/ siempre tenga reportes recientes y se eviten regresiones de seguridad.

### Qué hacer después de pegarlo
1) En el editor de conflictos de GitHub, **reemplazá todo** por el bloque de arriba.  
2) Click en **Mark as resolved** (o “Resolve”).  
3) Si aparece un botón **Commit merge** para ese archivo, hacelo.

Luego pasame **el siguiente archivo con conflicto** (pégalos con los marcadores `<<<<<<< ======= >>>>>>>`) y te devuelvo la versión final lista para pegar, igual que este.
