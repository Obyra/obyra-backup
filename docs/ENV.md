Inventario de entorno y dependencias

Este documento consolida las variables de entorno realmente usadas por la aplicación OBYRA y resume el estado de las dependencias. El objetivo es que cualquier persona pueda preparar entornos de desarrollo, staging y producción sin revisar todo el código.

1. Variables de entorno detectadas
Variable	Descripción	Uso principal
SECRET_KEY / SESSION_SECRET	Clave para firmar sesiones Flask. SESSION_SECRET tiene prioridad y cae en SECRET_KEY; si ninguna existe la app usa un valor inseguro.	app.py configura app.secret_key al arrancar.
DATABASE_URL	Cadena SQLAlchemy obligatoriamente con prefijo postgresql. La app falla si apunta a otro motor.	Configuración de base de datos en app.py antes de inicializar extensiones.
AUTO_CREATE_DB	Bandera heredada para creación automática sólo en scripts legacy que usen SQLite.	app.py/scripts antiguos.
WIZARD_BUDGET_BREAKDOWN_ENABLED	Activa el nuevo desglose del asistente de presupuestos.	_env_flag en app.py.
WIZARD_BUDGET_SHADOW_MODE	Ejecuta el asistente en modo sombra.	_env_flag en app.py.
SHOW_IA_CALCULATOR_BUTTON	Controla la visibilidad del botón de la calculadora IA.	_env_flag en app.py.
ENABLE_REPORTS	Habilita la generación de reportes (Matplotlib/WeasyPrint).	_env_flag en app.py.
ENABLE_GOOGLE_OAUTH_HELP	Muestra hints si faltan credenciales OAuth.	_env_flag en app.py.
MAPS_PROVIDER	Proveedor de geocodificación (nominatim por defecto).	app.py/servicios de geocodificación.
MAPS_API_KEY	Clave para proveedores de mapas que lo requieran.	app.py.
MAPS_USER_AGENT	User-Agent para Nominatim.	services/geocoding_service.py.
GEOCODE_CACHE_TTL	TTL del caché de geocodificación (segundos).	services/geocoding_service.py.
MP_ACCESS_TOKEN	Token Mercado Pago (sandbox/prod).	marketplace_payments.py (SDK).
MP_WEBHOOK_PUBLIC_URL	URL pública registrada. Debe apuntar a /api/market/payments/mp/webhook.	app.py/marketplace_payments.py.
PLATFORM_COMMISSION_RATE	Comisión del marketplace (decimal).	commission_utils.py/models.py.
BASE_URL	Dominio público para PDFs y enlaces.	marketplace/services/po_pdf.py.
STORAGE_DIR	Directorio local para archivos generados.	marketplace/services/po_pdf.py.
SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD	SMTP para notificaciones.	marketplace/services/emailer.py.
FROM_EMAIL	Remitente por defecto.	marketplace/services/emailer.py.
OPENAI_API_KEY	Credencial para calculadora IA.	calculadora_ia.py.
FX_PROVIDER	Fuente de tipo de cambio (bna).	presupuestos.py.
EXCHANGE_FALLBACK_RATE	Tasa alternativa manual.	presupuestos.py.
GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET	OAuth para login con Google.	auth.py.
PYTHONIOENCODING	Se fuerza a utf-8 para evitar errores en CLI.	_ensure_utf8_io() en app.py.

Checklist previo a cada despliegue

Secretos (SECRET_KEY, SESSION_SECRET, MP_ACCESS_TOKEN, SMTP_PASSWORD, OPENAI_API_KEY, GOOGLE_OAUTH_*) cargados en el gestor de secretos del entorno.

DATABASE_URL apunta a PostgreSQL administrado con TLS y backups.

MP_WEBHOOK_PUBLIC_URL responde 200 desde Internet y coincide con la ruta /api/market/payments/mp/webhook.

BASE_URL/STORAGE_DIR configurados según dominio y storage persistente.

Feature flags (ENABLE_REPORTS, WIZARD_*, SHOW_IA_CALCULATOR_BUTTON) documentados con su estado actual.

2. Configuración mínima por entorno
Variable	Desarrollo local	Staging	Producción
DATABASE_URL	postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev	postgresql+psycopg://obyra:<password>@staging-db:5432/obyra_stg	postgresql+psycopg://obyra:<password>@prod-db:5432/obyra_prod
SECRET_KEY / SESSION_SECRET	Valores simples pero únicos en .env.	En gestor de secretos por entorno.	Claves de alta entropía con rotación.
MP_ACCESS_TOKEN	Token sandbox.	Token staging.	Token productivo (vault).
MP_WEBHOOK_PUBLIC_URL	URL pública del túnel → /api/market/payments/mp/webhook	https://staging.tu-dominio.com/api/market/payments/mp/webhook	https://app.tu-dominio.com/api/market/payments/mp/webhook
BASE_URL	http://127.0.0.1:8080 (o el del túnel).	Dominio staging.	Dominio público.
SMTP_*	Mailhog/Mailtrap.	Cuenta transaccional sandbox.	Proveedor transaccional con TLS.
OPENAI_API_KEY	Key de pruebas.	Key aislada.	Key productiva con límites.
MAPS_PROVIDER / MAPS_API_KEY	nominatim o proveedor de pruebas.	Proveedor con key restringida.	Proveedor con SLA.
PLATFORM_COMMISSION_RATE	0.02 (default).	Ajustado a pruebas.	% oficial del marketplace.
FX_PROVIDER / EXCHANGE_FALLBACK_RATE	bna + fallback opcional.	Igual a prod.	Según política financiera.
3. Mercado Pago: verificación rápida local

Webhook oficial: POST /api/market/payments/mp/webhook

Prueba local:

curl -sS -X POST http://127.0.0.1:8080/api/market/payments/mp/webhook \
  -H "Content-Type: application/json" \
  -d '{"type":"payment","data":{"id":"test-id"}}'

Escenario	Respuesta esperada
Falta MP_ACCESS_TOKEN	503 con { "error": "Mercado Pago no está configurado" } (y log).
Evento ≠ payment	200 con { "status": "ignored" }.
payment válido	Flujo de actualización de orden (requiere token/SDK OK).
4. Estado de dependencias

Stack alineado: authlib~=1.6.5, flask~=3.1.1, flask-sqlalchemy~=3.1.1, flask-migrate~=4.0.7, sqlalchemy~=2.0.41, psycopg[binary]>=3.2,<3.3, werkzeug~=3.1.3, requests~=2.32.3, mercadopago~=2.3.0.

Removidas librerías huérfanas: email-validator, pyjwt.

Mantener (por flags): matplotlib, weasyprint, openai (posible mover a “extras” más adelante).

Si se modifica el set de paquetes, regenerar requirements.lock/archivo de tooling.

5. Auditoría periódica
Comando	Propósito	Salida actual
./scripts/audit_deps.sh	Ejecuta pip-audit, safety check y deptry . y guarda reportes en docs/audits/AAAAMMDD-*.txt.	En CI sin binarios, los reportes registran [missing] ….
pip check	Verifica conflictos de versiones instaladas.	Ejecutar tras instalar dependencias reales.

Siguiente paso recomendado: job de CI que instale dependencias de producción y ejecute ./scripts/audit_deps.sh + pip check, guardando artefactos en docs/audits/.