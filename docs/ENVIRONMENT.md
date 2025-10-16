# OBYRA – Guía mínima de entorno y dependencias (DEV / STAGING / PROD)

Este documento define la configuración mínima viable por entorno, variables requeridas, cómo levantar la base de datos PostgreSQL con Docker y cómo auditar dependencias.

---

## 1. Matriz de configuración por entorno

| Variable                          | DEV (local)                                   | STAGING                                         | PROD                                             |
|-----------------------------------|-----------------------------------------------|--------------------------------------------------|--------------------------------------------------|
| `FLASK_ENV`                       | `development`                                 | `production`                                     | `production`                                     |
| `FLASK_RUN_PORT`                  | `8080`                                        | (gestionado por WSGI/Reverse Proxy)              | (gestionado por WSGI/Reverse Proxy)              |
| `PYTHONIOENCODING`               | `utf-8`                                       | `utf-8`                                          | `utf-8`                                          |
| `SECRET_KEY`                      | **Generar** (ej.: `python -c "import secrets;print(secrets.token_urlsafe(32))"`) | **CREDENCIAL** (KMS/Secrets Manager) | **CREDENCIAL** (KMS/Secrets Manager) |
| `SESSION_SECRET`                  | `${SECRET_KEY}`                               | `${SECRET_KEY}`                                  | `${SECRET_KEY}`                                  |
| `DATABASE_URL`                    | `postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev` | `postgresql+psycopg://USER:PASS@HOST:PORT/DB`    | `postgresql+psycopg://USER:PASS@HOST:PORT/DB`    |
| `SQLALCHEMY_POOL_SIZE`            | `10`                                          | `20`                                             | `20`–`50` según carga                            |
| `SQLALCHEMY_MAX_OVERFLOW`         | `10`                                          | `20`                                             | `20`–`50`                                        |
| `SQLALCHEMY_POOL_TIMEOUT`         | `30`                                          | `30`                                             | `30`                                             |
| `BASE_URL`                        | `http://127.0.0.1:8080`                       | `https://staging.obyra.example`                  | `https://app.obyra.example`                      |
| `APP_BASE_URL`                    | `${BASE_URL}`                                 | `${BASE_URL}`                                    | `${BASE_URL}`                                    |
| `STORAGE_DIR`                     | `./storage`                                   | ruta persistente                                 | ruta persistente                                 |
| `ENABLE_REPORTS`                  | `1` o `0`                                     | `1`                                              | `1`                                              |
| `GOOGLE_OAUTH_CLIENT_ID`          | (vacío o credencial de pruebas)               | **CREDENCIAL**                                   | **CREDENCIAL**                                   |
| `GOOGLE_OAUTH_CLIENT_SECRET`      | (vacío o credencial de pruebas)               | **CREDENCIAL**                                   | **CREDENCIAL**                                   |
| `ENABLE_GOOGLE_OAUTH_HELP`        | `true`                                        | `false`                                          | `false`                                          |
| `MP_ACCESS_TOKEN`                 | **Sandbox** (si se prueba MP)                 | **Prod (secreto)**                                | **Prod (secreto)**                                |
| `MP_WEBHOOK_PUBLIC_URL`           | `http://127.0.0.1:8080/api/market/payments/mp/webhook` | `https://staging.obyra.example/api/market/payments/mp/webhook` | `https://app.obyra.example/api/market/payments/mp/webhook` |
| `SMTP_HOST` / `SMTP_PORT`         | Mailtrap (dev)                                | Proveedor transaccional (SendGrid/SES/etc.)       | Proveedor transaccional                           |
| `SMTP_USER` / `SMTP_PASS`         | credenciales dev                              | **CREDENCIAL**                                    | **CREDENCIAL**                                    |
| `FROM_EMAIL` / `MAIL_FROM`        | `OBYRA IA <no-reply@obyra.local>`             | `no-reply@staging.obyra.example`                 | `no-reply@app.obyra.example`                     |
| `MAPS_PROVIDER`                   | `nominatim`                                   | `nominatim` o provider con API key               | provider con API key                              |
| `MAPS_API_KEY`                    | (vacío si `nominatim`)                        | **CREDENCIAL si aplica**                          | **CREDENCIAL si aplica**                          |
| `MAPS_USER_AGENT`                 | `obyra-dev-bot`                               | `obyra-stg-bot`                                   | `obyra-prod-bot`                                  |
| `GEOCODE_CACHE_TTL`               | `3600`                                        | `3600`–`21600`                                    | `3600`–`21600`                                    |
| `FX_PROVIDER` / `EXCHANGE_FALLBACK_RATE` | `bna` / `0`                          | `bna` o servicio externo                          | servicio externo confiable                        |
| `OPENAI_API_KEY`                  | (opcional)                                    | **CREDENCIAL** (si se usa)                        | **CREDENCIAL** (si se usa)                        |
| Flags `WIZARD_*`, `SHOW_IA_CALCULATOR_BUTTON` | según QA                      | según QA                                         | según producto                                    |
| `PLATFORM_COMMISSION_RATE`        | `0.02`                                        | según negocio                                     | según negocio                                     |

> **Importante**: en todos los entornos usamos **PostgreSQL** (driver `psycopg` 3). Evitar SQLite.

---

## 2. Puesta en marcha (DEV – Windows/PowerShell)

### 2.1. Base de datos con Docker
```powershell
docker rm -f obyra-pg 2>$null
docker run --name obyra-pg -p 5433:5432 \
  -e POSTGRES_USER=obyra \
  -e POSTGRES_PASSWORD=obyra \
  -e POSTGRES_DB=obyra_dev \
  -d postgres:16

2.2. Entorno virtual e instalación
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -r requirements.txt

2.3. Variables mínimas de sesión y run
$env:FLASK_APP="app.py"
$env:FLASK_ENV="development"
$env:FLASK_RUN_PORT="8080"
$env:PYTHONIOENCODING="utf-8"
$env:DATABASE_URL="postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev"

# Primer upgrade + arranque
python -m flask db upgrade
python -m flask run --port 8080
```

## 3. Auditoría de dependencias

Ejecutar en un entorno aislado (venv), con requirements.txt actualizado.

### 3.1. Herramientas
```powershell
pip install pip-audit safety deptry
```

### 3.2. Comandos
```powershell
# CVEs conocidos en deps instaladas
pip-audit

# CVEs contra requirements.txt
pip-audit -r requirements.txt

# Reglas de seguridad ampliadas
safety check --full-report

# Descubrir dependencias huérfanas / no usadas
deptry .
```

### 3.3. Criterios de limpieza

Unificar PostgreSQL en psycopg 3 (psycopg).

Remover psycopg2-binary y psycopg-binary si no son necesarias.

Eliminar libs no referenciadas en el código.

Congelar versiones mínimas seguras si hay CVEs.

Documentar hallazgos y cambios en PR.

## 4. Notas de integración externas

- **Google OAuth (opcional en dev)**: crear Client ID/Secret y setear `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`.
  - Callback típico: `${BASE_URL}/login/google/callback`.
- **Mercado Pago**: por ahora omitido (no hay `mk_orders` implementado). Dejar variables preparadas para cuando se implemente.
- **SMTP**: en DEV usar Mailtrap; en STAGING/PROD proveedor transaccional (p. ej. SendGrid/SES). Mantener `FROM_EMAIL` coherente con el dominio.

## 5. Migraciones y bootstrap

```powershell
python -m flask db upgrade
```

Si un entorno fresco necesita bootstrap de tablas básicas y no hay migraciones iniciales, usar script temporal con `db.create_all()` (solo dev/staging y con `AUTO_CREATE_DB=1` si se implementa esta guarda).

## 6. Troubleshooting rápido

- “DATABASE_URL debe usar PostgreSQL”: asegurar que la variable de proceso apunta a `postgresql+psycopg://…`. Limpiar variables de usuario/máquina si pisan el valor.
- “relation X does not exist”: correr `flask db upgrade`.
- **WeasyPrint**: requiere binarios del sistema para render PDF; en dev se puede desactivar `ENABLE_REPORTS=0`.
- **Puerto ocupado (8080)**:

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
$pid8080 = (Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($pid8080) { Stop-Process -Id $pid8080 -Force }
```

## 7. Valores por defecto seguros (DEV)

| Variable | Valor sugerido | Comentario |
|----------|----------------|------------|
| `DATABASE_URL` | `postgresql+psycopg://obyra:obyra@localhost:5433/obyra_dev` | Contenedor local de PostgreSQL 16 expuesto en 5433. |
| `SECRET_KEY` | `changeme-dev-secret` | Reemplazar por secreto fuerte generado con `secrets.token_urlsafe`. |
| `BASE_URL` / `APP_BASE_URL` | `http://127.0.0.1:8080` | Mantener coherente con `FLASK_RUN_PORT`. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | `smtp.mailtrap.io` / `2525` / `<user>` / `<pass>` | Usar inbox de Mailtrap para pruebas locales. |
| `FX_PROVIDER` | `bna` | Tasas oficiales del Banco Nación, sin claves adicionales. |
| `MAPS_PROVIDER` / `MAPS_USER_AGENT` | `nominatim` / `obyra-dev-bot` | Nominatim sin API key, respetar user agent. |
| `ENABLE_REPORTS` | `1` | Activar reportes PDF; cambiar a `0` si faltan dependencias de WeasyPrint. |

### Smoke test post-setup

1. `python -m flask db upgrade`
2. `python -m flask run --port 8080`
3. Abrir `http://127.0.0.1:8080/reportes/dashboard` y verificar respuesta HTTP 200.
