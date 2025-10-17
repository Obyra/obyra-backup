Inventario de entorno y dependencias

Este documento consolida las variables de entorno realmente usadas por la aplicación OBYRA y resume el estado de las dependencias. El objetivo es que cualquier persona pueda preparar entornos de desarrollo, staging y producción sin revisar todo el código.

1. Variables de entorno detectadas
Variable	Descripción	Uso principal
SECRET_KEY / SESSION_SECRET	Clave para firmar sesiones Flask. SESSION_SECRET tiene prioridad; si ninguna existe, la app usa un valor inseguro (solo dev).	app.py → app.secret_key
DATABASE_URL	Cadena SQLAlchemy con prefijo postgresql (en tests puede usarse sqlite:///:memory:). Si es Neon y no trae sslmode, se fuerza sslmode=require.	Config DB en app.py antes de inicializar extensiones
AUTO_CREATE_DB	Solo crea schema si la URI es SQLite (útil para scripts locales/legacy). No aplica a Postgres.	Helper maybe_create_sqlite_schema()
WIZARD_BUDGET_BREAKDOWN_ENABLED	Activa el nuevo desglose del asistente de presupuestos.	_env_flag en app.py
WIZARD_BUDGET_SHADOW_MODE	Ejecuta el asistente en “modo sombra”.	_env_flag en app.py
SHOW_IA_CALCULATOR_BUTTON	Muestra/oculta el botón de calculadora IA.	_env_flag en app.py
ENABLE_REPORTS	Habilita reportes (Matplotlib/WeasyPrint).	_env_flag en app.py
ENABLE_GOOGLE_OAUTH_HELP	Mensajes de ayuda para configurar OAuth.	_env_flag en app.py
MAPS_PROVIDER	Proveedor de geocodificación (nominatim por defecto).	app.py y servicios de geocoding
MAPS_API_KEY	API key para mapas (si el proveedor lo requiere).	app.py/servicios
MAPS_USER_AGENT	User-Agent para Nominatim.	services/geocoding_service.py
GEOCODE_CACHE_TTL	TTL del caché de geocodificación (seg).	services/geocoding_service.py
MP_ACCESS_TOKEN	Token de Mercado Pago (sandbox/prod).	Inicialización/SDK MP y validaciones en arranque
MP_WEBHOOK_PUBLIC_URL	URL pública registrada en MP → debe apuntar a /api/payments/mp/webhook.	Log de arranque en app.py y notification_url
PLATFORM_COMMISSION_RATE	Comisión del marketplace (decimal).	commission_utils.py, models.py, órdenes
BASE_URL	Dominio público usado en PDFs y enlaces.	marketplace/services/po_pdf.py
STORAGE_DIR	Directorio local para archivos generados.	marketplace/services/po_pdf.py
SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD	SMTP para notificaciones.	marketplace/services/emailer.py
FROM_EMAIL	Remitente por defecto.	marketplace/services/emailer.py
OPENAI_API_KEY	Credencial para calculadora IA.	calculadora_ia.py
FX_PROVIDER	Fuente del tipo de cambio (bna por defecto).	services/exchange/*, presupuestos.py
EXCHANGE_FALLBACK_RATE	Tasa de cambio alternativa manual.	services/exchange/*
GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET	OAuth para login con Google.	auth.py
PYTHONIOENCODING	Forzada a utf-8 para evitar errores en CLI.	_ensure_utf8_io() en app.py

Checklist antes de desplegar

Secretos (SESSION_SECRET/SECRET_KEY, MP_ACCESS_TOKEN, SMTP_PASSWORD, OPENAI_API_KEY, GOOGLE_OAUTH_*) en el gestor de secretos.

DATABASE_URL → PostgreSQL administrado con TLS/backups (Neon: verificar sslmode=require).

MP_WEBHOOK_PUBLIC_URL responde 200 y apunta a /api/payments/mp/webhook.

BASE_URL / STORAGE_DIR configurados según dominio y storage persistente.

Feature flags (ENABLE_REPORTS, WIZARD_*, SHOW_IA_CALCULATOR_BUTTON) documentados con su estado.

2. Configuración mínima por entorno
Variable	Desarrollo local	Staging	Producción
DATABASE_URL	postgresql+psycopg://obyra:password@localhost:5433/obyra_dev	postgresql+psycopg://obyra:<password>@staging-db:5432/obyra_stg	postgresql+psycopg://obyra:<password>@prod-db:5432/obyra_prod
SECRET_KEY / SESSION_SECRET	Valores simples pero únicos en .env.	En gestor de secretos por entorno.	Claves de alta entropía con rotación.
MP_ACCESS_TOKEN	Token sandbox.	Token staging.	Token productivo (vault).
MP_WEBHOOK_PUBLIC_URL	Túnel público → /api/payments/mp/webhook.	https://staging.tu-dominio.com/api/payments/mp/webhook	https://app.tu-dominio.com/api/payments/mp/webhook
BASE_URL	http://127.0.0.1:8080 (o dominio del túnel).	Dominio staging.	Dominio público oficial.
SMTP_*	Mailhog/Mailtrap.	Cuenta transaccional sandbox.	Proveedor transaccional con TLS.
OPENAI_API_KEY	Key de pruebas.	Key aislada de staging.	Key productiva con límites.
MAPS_PROVIDER / MAPS_API_KEY	nominatim o proveedor de pruebas.	Proveedor con key restringida.	Proveedor con SLA/quotas.
PLATFORM_COMMISSION_RATE	0.02.	Según pruebas.	% oficial.
FX_PROVIDER / EXCHANGE_FALLBACK_RATE	bna + fallback opcional.	Igual a prod.	Política financiera.
3. Mercado Pago: pruebas y verificación

La app loguea al inicio MP webhook URL: ... si la variable está presente y muestra warning si falta.

Webhook oficial: POST /api/payments/mp/webhook.

Health local (si existe): GET /api/payments/mp/health → {"ok": true, "webhook": <bool>}.

Prueba rápida local

curl -sS -X POST http://127.0.0.1:8080/api/payments/mp/webhook \
  -H "Content-Type: application/json" \
  -d '{"type":"payment","data":{"id":"test-id"}}'

Escenario	Respuesta esperada
Falta MP_ACCESS_TOKEN	503 con {"error":"Mercado Pago no está configurado"} y log de error.
Evento que no es payment	200 con {"status":"ignored"}.
Evento payment válido	Flujo de actualización de orden (requiere token/SDK).
4. Estado de dependencias

Versionado alineado con el stack actual:
authlib~=1.6.5, flask~=3.1.1, flask-sqlalchemy~=3.1.1, flask-migrate~=4.0.7,
sqlalchemy~=2.0.41, psycopg[binary]>=3.2,<3.3, werkzeug~=3.1.3,
requests~=2.32.3, mercadopago~=2.3.0.

Bibliotecas pesadas que se mantienen por flags: matplotlib, weasyprint, openai (evaluar mover a extras cuando se delimite su uso).

Librerías sin uso (removidas): email-validator, pyjwt (no hay importaciones activas).

Existe requirements.lock para tooling (black, isort, ruff, etc.). Regenerar al cambiar versiones o herramientas.

5. Auditoría periódica
Comando	Propósito	Nota
./scripts/audit_deps.sh	Corre pip-audit, safety check y deptry ., guardando reportes en docs/audits/AAAAMMDD-*.txt.	Configurar en CI para instalar deps reales y almacenar reportes.
pip check	Verifica conflictos de versiones instaladas.	Ejecutar tras pip install -r requirements.txt.

Siguiente paso recomendado: agregar un job de CI que instale las dependencias de producción y ejecute ./scripts/audit_deps.sh + pip check, de modo que docs/audits/ siempre tenga reportes recientes y se eviten regresiones de seguridad.