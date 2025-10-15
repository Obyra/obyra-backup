# Configuración de entornos para OBYRA

Este documento resume las variables de entorno y dependencias críticas identificadas en el código actual. Su objetivo es servir como guía mínima para preparar entornos de **staging** y **producción** mientras se avanza con la migración a PostgreSQL.

## 1. Variables centrales de seguridad y base de datos

| Variable | Uso y valor por defecto | Recomendación staging | Recomendación producción | Observaciones |
| --- | --- | --- | --- | --- |
| `SECRET_KEY` / `SESSION_SECRET` | Se usa como `app.secret_key`; si no está definida se cae en `"dev-secret-key-change-me"`. 【F:app.py†L68-L106】 | Generar clave aleatoria de ≥32 bytes, rotarla manualmente si se sospecha fuga. | Gestionar mediante gestor de secretos (AWS Secrets Manager, GCP Secret Manager) con rotación programada. | Consolidar en una sola variable (`SECRET_KEY`) y eliminar fallback inseguro.
| `DATABASE_URL` | Configura SQLAlchemy; si falta, se usa `sqlite:///tmp/dev.db` y se crea la carpeta automáticamente. 【F:app.py†L108-L158】 | Cadena `postgresql+psycopg://usuario:password@host:5432/obyra_stg` con SSL requerido si aplica. | Cadena `postgresql+psycopg://usuario:password@host:5432/obyra_prod` gestionada por la plataforma (RDS, Cloud SQL). | Ajustar parámetros de pool (`pool_size`, `max_overflow`) tras dimensionar workers y plan de conexión.
| `PYTHONIOENCODING` | Forzado a `utf-8` para evitar problemas de consola. 【F:app.py†L33-L84】 | Mantener valor por defecto. | Mantener valor por defecto. | No requiere cambios.

## 2. Flags de funcionalidad

| Variable | Comportamiento actual | Recomendación |
| --- | --- | --- |
| `WIZARD_BUDGET_BREAKDOWN_ENABLED` | Activa desglose del nuevo presupuestador (por defecto `False`). 【F:app.py†L164-L172】 | Activar primero en staging para validación funcional; documentar toggles en tablero de cambios. |
| `WIZARD_BUDGET_SHADOW_MODE` | Ejecuta lógica en modo sombra (default `False`). 【F:app.py†L164-L172】 | Usar en staging para medir impacto sin exponer a usuarios. |
| `SHOW_IA_CALCULATOR_BUTTON` | Muestra botón del calculador IA (default `False`). 【F:app.py†L172-L176】 | Habilitar bajo feature flag controlado. |
| `ENABLE_REPORTS` | Activa servicio de reportes con Matplotlib (default `False`). 【F:app.py†L172-L177】 | Encender solo cuando SMTP y almacenamiento estén listos; probar en staging. |
| `ENABLE_GOOGLE_OAUTH_HELP` | Habilita mensaje de ayuda si faltan credenciales de Google. 【F:auth.py†L101-L133】 | Mantener `False` en producción; útil en entornos de desarrollo. |

## 3. Proveedores externos y servicios auxiliares

| Área | Variables | Uso y default | Valores sugeridos |
| --- | --- | --- | --- |
| **Autenticación Google** | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | Registra proveedor OAuth solo si ambas están definidas. 【F:auth.py†L101-L133】【F:main_app.py†L13-L52】 | Emitir credenciales separadas para staging y producción. Configurar redirect URIs correspondientes a cada dominio. |
| **Mercado Pago** | `MP_ACCESS_TOKEN`, `MP_WEBHOOK_PUBLIC_URL` (esperadas en `current_app.config`) | El SDK se inicializa con `current_app.config['MP_ACCESS_TOKEN']`; sin token las operaciones fallan. 【F:marketplace_payments.py†L1-L189】 | Definir variables de entorno e incorporarlas a la configuración de Flask (`app.config`) durante bootstrap. Usar tokens diferentes por ambiente y registrar webhook público específico. |
| **Correo SMTP** | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `FROM_EMAIL` | `marketplace/services/emailer.py` lee directamente de entorno; `services/email_service.py` espera la misma información en `app.config`. 【F:marketplace/services/emailer.py†L20-L75】【F:services/email_service.py†L23-L74】 | Centralizar carga en `app.config` desde variables de entorno y validar con pruebas de humo. Para staging usar cuenta sandbox; en producción requerir TLS y contraseñas de aplicación. |
| **Mapas / Geocoding** | `MAPS_PROVIDER` (`nominatim` por defecto), `MAPS_API_KEY`, `MAPS_USER_AGENT`, `GEOCODE_CACHE_TTL` | Configuran proveedor y caché de geocodificación. 【F:app.py†L168-L177】【F:services/geocoding_service.py†L17-L40】 | Mantener `nominatim` para pruebas; en producción evaluar proveedor con SLA (Google Maps, Mapbox) y definir `MAPS_API_KEY` + `MAPS_USER_AGENT` acorde a políticas. |
| **Cambio de divisas** | `FX_PROVIDER` (default `bna`), `EXCHANGE_FALLBACK_RATE` | Selecciona proveedor de tipo de cambio; permite fallback manual. 【F:presupuestos.py†L152-L164】 | Configurar proveedor estable en producción y definir un fallback actualizado diariamente. |
| **IA / OpenAI** | `OPENAI_API_KEY` | Inicializa cliente OpenAI. 【F:calculadora_ia.py†L1-L32】 | Requerido solo si se habilita funcionalidad IA; usar claves separadas por entorno y política de rotación. |
| **Comisiones** | `PLATFORM_COMMISSION_RATE` | Determina fee de la plataforma (default 0.02). 【F:commission_utils.py†L1-L96】【F:models.py†L2444-L2451】 | Validar valor con negocio antes de exponer a producción; documentar mecanismo de cambios. |
| **Almacenamiento de PDFs** | `STORAGE_DIR` (default `./storage`) | Directorio para órdenes de compra y PDFs. 【F:marketplace/services/po_pdf.py†L1-L230】 | En producción apuntar a volumen persistente; en staging limpiar periódicamente. |
| **Base URL pública** | `BASE_URL` (default `http://localhost:5000`) | Se usa al generar PDFs y enlaces. 【F:marketplace/services/po_pdf.py†L200-L230】 | Establecer dominio real de cada ambiente para evitar enlaces rotos. |

## 4. Configuración mínima viable por entorno

- **Desarrollo local**
  1. Definir `MP_ACCESS_TOKEN` con un token de prueba/sandbox y `MP_WEBHOOK_PUBLIC_URL` apuntando a una URL pública provista por un túnel (por ejemplo `https://<subdominio>.ngrok.io/api/payments/mp/webhook`).
  2. Iniciar el túnel con herramientas como `ngrok http 5000 --hostname=<subdominio>.ngrok.io` o `cloudflared tunnel --url http://localhost:5000` y confirmar que la URL exponga `/api/payments/mp/webhook`.
  3. **No** utilizar `http://127.0.0.1` ni `http://localhost`, ya que Mercado Pago no puede realizar callbacks a direcciones locales.
  4. Documentar las URLs generadas en cada sesión y actualizarlas en el panel de notificaciones de Mercado Pago.

- **Staging**
  1. Definir `SECRET_KEY` y `DATABASE_URL` apuntando a base PostgreSQL de pruebas con SSL obligatorio.
  2. Configurar credenciales separadas para Google OAuth, Mercado Pago (modo sandbox), SMTP (sandbox) y OpenAI si se valida IA.
  3. Establecer `BASE_URL`, `MAPS_PROVIDER`, `MAPS_API_KEY` y `STORAGE_DIR` para el dominio de staging. Para Mercado Pago, usar dominios reales (por ejemplo `https://staging.tu-dominio.com/api/payments/mp/webhook`) y registrar la URL en el panel de notificaciones.
  4. Activar flags (`WIZARD_BUDGET_SHADOW_MODE`, `ENABLE_REPORTS`) solo mientras se monitorea su impacto.
  5. Documentar en un `.env.staging` o gestor de secretos la lista completa anterior y compartir acceso controlado.

- **Producción**
  1. Gestionar `SECRET_KEY`, tokens OAuth, SMTP y Mercado Pago en gestor de secretos con rotación y registros de acceso.
  2. Utilizar `DATABASE_URL` apuntando a clúster administrado con backups automáticos y parámetros de pool ajustados al número de workers.
  3. Definir `BASE_URL` y `STORAGE_DIR` en infraestructura persistente (S3 o volumen replicado) y revisar permisos de lectura/escritura. Registrar `MP_WEBHOOK_PUBLIC_URL` con el dominio público definitivo (por ejemplo `https://app.tu-dominio.com/api/payments/mp/webhook`).
  4. Fijar `PLATFORM_COMMISSION_RATE`, `FX_PROVIDER` y `EXCHANGE_FALLBACK_RATE` según políticas comerciales y revisarlos antes de cada release.
  5. Mantener feature flags documentados; habilitar solo tras validar en staging y con estrategia de rollback.

## 5. Auditoría de dependencias

- El proyecto declara dependencias exclusivamente en `pyproject.toml` con especificadores `>=`, lo que habilita actualizaciones mayores automáticas y puede introducir regresiones o vulnerabilidades no controladas. 【F:pyproject.toml†L1-L31】
- No existe un `requirements.txt` separado; se recomienda generar un archivo de bloqueo (`uv lock`, `pip-tools`, `poetry.lock`) y revisar periódicamente con herramientas como `pip-audit` o Dependabot.
- Dependencias de peso como `matplotlib`, `weasyprint`, `openai` y `mercadopago` se usan en partes específicas del código (`reports_service`, generación de PDFs, calculadora IA, marketplace). Validar si todas son necesarias en el despliegue inicial y mover las opcionales a extras para reducir superficie de ataque.
- Revisar versiones mínimas exigidas: por ejemplo, `flask>=3.1.1` y `sqlalchemy>=2.0.41` requieren Python 3.10+; coordinar con el runtime seleccionado para evitar incompatibilidades.

## 6. Próximos pasos sugeridos

1. Incluir la carga de todas las variables anteriores en el proceso de inicialización de Flask (`create_app`) y validar su presencia con asserts o logs claros.
2. Añadir ejemplos de `.env.example` con valores dummy pero formato correcto para facilitar onboarding.
3. Automatizar un chequeo en CI que verifique la existencia de secretos críticos antes del despliegue (por ejemplo, script que falle si `SECRET_KEY` conserva el valor por defecto).
4. Programar auditoría trimestral de dependencias y credenciales para asegurar cumplimiento de políticas de seguridad.
