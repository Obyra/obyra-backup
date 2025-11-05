# 🏗️ OBYRA - Plataforma de Gestión de Proyectos de Construcción

Sistema integral para la gestión de obras, presupuestos, inventario, equipos, marketplace y más.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-red.svg)](https://redis.io/)
[![License](https://img.shields.io/badge/License-Proprietary-orange.svg)]()

---

## 📋 Tabla de Contenidos

- [Características](#-características)
- [Requisitos del Sistema](#-requisitos-del-sistema)
- [Instalación Rápida](#-instalación-rápida)
  - [Opción 1: Instalación Local (Desarrollo)](#opción-1-instalación-local-desarrollo)
  - [Opción 2: Instalación con Docker (Producción)](#opción-2-instalación-con-docker-producción)
- [Configuración](#-configuración)
- [Cómo Ejecutar](#-cómo-ejecutar)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Scripts Útiles](#-scripts-útiles)
- [Troubleshooting](#-troubleshooting)
- [Documentación Adicional](#-documentación-adicional)

---

## ✨ Características

### Gestión de Proyectos
- ✅ Creación y seguimiento de obras
- ✅ Etapas y tareas con asignación de responsables
- ✅ Control de avances con certificaciones
- ✅ Generación de reportes PDF
- ✅ Dashboard con métricas en tiempo real

### Presupuestos Inteligentes
- ✅ Wizard de creación de presupuestos paso a paso
- ✅ Integración con precios de mercado
- ✅ Análisis de costos y márgenes
- ✅ Exportación a Excel y PDF
- ✅ Calculadora IA (opcional, requiere OpenAI API)

### Marketplace
- ✅ Portal de proveedores
- ✅ Cotizaciones y órdenes de compra
- ✅ Integración con Mercado Pago
- ✅ Sistema de comisiones configurable

### Inventario y Equipos
- ✅ Gestión de inventario con categorías
- ✅ Control de stock y movimientos
- ✅ Asignación de equipos a obras
- ✅ Mantenimiento preventivo

### Seguridad y Multi-tenancy
- ✅ Sistema de organizaciones independientes
- ✅ Roles y permisos granulares (RBAC)
- ✅ Autenticación con Google OAuth (opcional)
- ✅ Rate limiting y protección contra abuso
- ✅ Logging de auditoría completo

### Performance
- ✅ Redis caching para queries frecuentes
- ✅ Índices optimizados en PostgreSQL
- ✅ Compresión gzip en Nginx
- ✅ Tareas asíncronas con Celery

---

## 🖥️ Requisitos del Sistema

### Hardware Mínimo (Desarrollo)
- CPU: 2 cores
- RAM: 4 GB
- Disco: 10 GB libres

### Hardware Recomendado (Producción)
- CPU: 4+ cores
- RAM: 8+ GB
- Disco: 50+ GB libres (SSD recomendado)

### Software Necesario

#### Para Instalación Local:
- **Python**: 3.11 o superior
- **PostgreSQL**: 14 o superior (16 recomendado)
- **Redis**: 6 o superior (7 recomendado)
- **Git**: Para clonar el repositorio

#### Para Instalación con Docker:
- **Docker Engine**: 20.10 o superior
- **Docker Compose**: 2.0 o superior

---

## 🚀 Instalación Rápida

### Opción 1: Instalación Local (Desarrollo)

**Ideal para**: Desarrollo, testing, contribuir al proyecto

#### 1️⃣ Clonar el Repositorio

```bash
# Clonar el proyecto
git clone <repository-url> obyra
cd obyra

# Verificar que estás en la rama correcta
git branch
```

#### 2️⃣ Instalar PostgreSQL

<details>
<summary><b>🐧 Linux (Ubuntu/Debian)</b></summary>

```bash
# Instalar PostgreSQL
sudo apt update
sudo apt install postgresql postgresql-contrib

# Iniciar servicio
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Crear usuario y base de datos
sudo -u postgres psql <<EOF
CREATE USER obyra WITH PASSWORD 'obyra_dev_password';
CREATE DATABASE obyra_dev OWNER obyra;
GRANT ALL PRIVILEGES ON DATABASE obyra_dev TO obyra;
EOF
```
</details>

<details>
<summary><b>🍎 macOS</b></summary>

```bash
# Instalar con Homebrew
brew install postgresql@16

# Iniciar servicio
brew services start postgresql@16

# Crear usuario y base de datos
psql postgres <<EOF
CREATE USER obyra WITH PASSWORD 'obyra_dev_password';
CREATE DATABASE obyra_dev OWNER obyra;
GRANT ALL PRIVILEGES ON DATABASE obyra_dev TO obyra;
EOF
```
</details>

<details>
<summary><b>🪟 Windows</b></summary>

1. Descargar PostgreSQL desde: https://www.postgresql.org/download/windows/
2. Ejecutar instalador y seguir wizard
3. Abrir pgAdmin o SQL Shell (psql)
4. Ejecutar:

```sql
CREATE USER obyra WITH PASSWORD 'obyra_dev_password';
CREATE DATABASE obyra_dev OWNER obyra;
GRANT ALL PRIVILEGES ON DATABASE obyra_dev TO obyra;
```
</details>

#### 3️⃣ Instalar Redis

<details>
<summary><b>🐧 Linux (Ubuntu/Debian)</b></summary>

```bash
# Instalar Redis
sudo apt install redis-server

# Iniciar servicio
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Verificar
redis-cli ping  # Debe responder: PONG
```
</details>

<details>
<summary><b>🍎 macOS</b></summary>

```bash
# Instalar con Homebrew
brew install redis

# Iniciar servicio
brew services start redis

# Verificar
redis-cli ping  # Debe responder: PONG
```
</details>

<details>
<summary><b>🪟 Windows</b></summary>

1. Descargar Redis desde: https://github.com/microsoftarchive/redis/releases
2. Extraer y ejecutar `redis-server.exe`
3. O usar Windows Subsystem for Linux (WSL) con instrucciones de Linux
</details>

#### 4️⃣ Configurar Python y Dependencias

```bash
# Verificar versión de Python
python3 --version  # Debe ser 3.11 o superior

# Crear entorno virtual
python3 -m venv venv

# Activar entorno virtual
# En Linux/macOS:
source venv/bin/activate

# En Windows:
venv\Scripts\activate

# Actualizar pip
pip install --upgrade pip setuptools wheel

# Instalar dependencias
pip install -r requirements.txt
```

**Nota**: Si hay errores con WeasyPrint o psycopg, ver sección de [Troubleshooting](#-troubleshooting).

#### 5️⃣ Configurar Variables de Entorno

```bash
# Copiar archivo de ejemplo
cp .env.example .env

# Editar .env con tu editor favorito
nano .env
# O
code .env
```

**Configuración mínima en `.env`:**

```env
# Flask
SECRET_KEY=dev-secret-key-change-in-production
FLASK_ENV=development
FLASK_DEBUG=1

# Database (ajustar si usaste otros valores)
DATABASE_URL=postgresql+psycopg://obyra:obyra_dev_password@localhost:5432/obyra_dev
ALEMBIC_DATABASE_URL=postgresql+psycopg://obyra:obyra_dev_password@localhost:5432/obyra_dev

# Redis
REDIS_URL=redis://localhost:6379/0
RATE_LIMITER_STORAGE=redis://localhost:6379/1

# Email (opcional para desarrollo)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu_email@gmail.com
SMTP_PASSWORD=tu_app_password
FROM_EMAIL=noreply@obyra.com

# Feature Flags
ENABLE_REPORTS=1
```

#### 6️⃣ Ejecutar Migraciones

```bash
# Aplicar migraciones a la base de datos
python -m flask db upgrade

# Verificar que se crearon las tablas
psql -U obyra -d obyra_dev -c "\dt"
```

#### 7️⃣ (Opcional) Poblar Base de Datos con Datos de Ejemplo

```bash
# Crear usuario administrador inicial
python configurar_admin.py

# Poblar datos de ejemplo (categorías de inventario, etc.)
python seed_inventory_categories.py
python seed_equipos_inventario.py
```

#### 8️⃣ Ejecutar la Aplicación

```bash
# Método 1: Flask development server (más simple)
python app.py

# Método 2: Gunicorn (más parecido a producción)
gunicorn --bind 0.0.0.0:5000 --workers 4 --threads 2 --reload app:app
```

**La aplicación estará disponible en**: http://localhost:5000

---

### Opción 2: Instalación con Docker (Producción)

**Ideal para**: Producción, staging, deployments

#### 1️⃣ Clonar el Repositorio

```bash
git clone <repository-url> obyra
cd obyra
```

#### 2️⃣ Configurar Variables de Entorno

```bash
# Copiar archivo de ejemplo
cp .env.example .env

# Editar con valores de producción
nano .env
```

**Configuración mínima para producción:**

```env
# Flask
FLASK_ENV=production
SECRET_KEY=<generar_con_python_-c_"import secrets; print(secrets.token_urlsafe(32))">

# PostgreSQL
POSTGRES_DB=obyra_prod
POSTGRES_USER=obyra
POSTGRES_PASSWORD=<contraseña_segura_aquí>
POSTGRES_MIGRATOR_USER=obyra_migrator
POSTGRES_MIGRATOR_PASSWORD=<otra_contraseña_segura>

# Redis
REDIS_URL=redis://redis:6379/0
RATE_LIMITER_STORAGE=redis://redis:6379/1

# Application
BASE_URL=https://tu-dominio.com

# Email (obligatorio en producción)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu_email@gmail.com
SMTP_PASSWORD=tu_app_password
FROM_EMAIL=noreply@tu-dominio.com

# Payments (si usas Mercado Pago)
MP_ACCESS_TOKEN=tu_access_token
MP_WEBHOOK_PUBLIC_URL=https://tu-dominio.com/webhook/mercadopago
PLATFORM_COMMISSION_RATE=0.10

# AI (opcional)
OPENAI_API_KEY=sk-...

# OAuth Google (opcional)
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...

# Maps/Geocoding
MAPS_PROVIDER=nominatim
MAPS_USER_AGENT=OBYRA/1.0

# Feature Flags
ENABLE_REPORTS=1
```

#### 3️⃣ Iniciar Servicios

```bash
# Desarrollo (con hot reload)
docker-compose -f docker-compose.dev.yml up -d

# Producción
docker-compose up -d

# Ver logs
docker-compose logs -f app

# Ver estado de servicios
docker-compose ps
```

#### 4️⃣ Acceder a la Aplicación

**Desarrollo:**
- App: http://localhost:5002

**Producción:**
- App detrás de Nginx: http://localhost:8080
- HTTPS: https://localhost:8443 (requiere certificados SSL)

#### 5️⃣ Comandos Útiles de Docker

```bash
# Ver logs de un servicio específico
docker-compose logs -f app
docker-compose logs -f postgres
docker-compose logs -f redis

# Ejecutar comandos dentro del contenedor
docker-compose exec app python app.py shell
docker-compose exec app flask db upgrade
docker-compose exec postgres psql -U obyra -d obyra_prod

# Reiniciar servicios
docker-compose restart app

# Detener todo
docker-compose down

# Detener y eliminar volúmenes (CUIDADO: borra datos)
docker-compose down -v

# Reconstruir imágenes
docker-compose build
docker-compose up -d --build
```

---

## ⚙️ Configuración

### Variables de Entorno Importantes

| Variable | Descripción | Requerido | Ejemplo |
|----------|-------------|-----------|---------|
| `SECRET_KEY` | Clave secreta de Flask para sesiones | ✅ Sí | `secrets.token_urlsafe(32)` |
| `FLASK_ENV` | Entorno: `development` o `production` | ✅ Sí | `development` |
| `DATABASE_URL` | URL de PostgreSQL | ✅ Sí | `postgresql+psycopg://user:pass@localhost/db` |
| `REDIS_URL` | URL de Redis | ✅ Sí | `redis://localhost:6379/0` |
| `SMTP_*` | Configuración de email | ⚠️ Producción | Ver ejemplo arriba |
| `OPENAI_API_KEY` | OpenAI para calculadora IA | ❌ No | `sk-...` |
| `GOOGLE_OAUTH_*` | Google OAuth login | ❌ No | Ver Google Console |
| `MP_ACCESS_TOKEN` | Mercado Pago | ❌ No | Token de MP |

### Configurar Super Admin

El sistema ya NO usa emails hardcodeados para super admins (mejora de seguridad).

Para otorgar privilegios de super admin:

```bash
# Método 1: Usando psql
psql -U obyra -d obyra_dev -c \
  "UPDATE usuarios SET is_super_admin = true WHERE email = 'admin@tu-empresa.com';"

# Método 2: Usando Python shell
python <<EOF
from app import app, db
from models import Usuario

with app.app_context():
    admin = Usuario.query.filter_by(email='admin@tu-empresa.com').first()
    if admin:
        admin.is_super_admin = True
        db.session.commit()
        print(f"✅ Super admin configurado: {admin.email}")
    else:
        print("❌ Usuario no encontrado")
EOF
```

---

## 🏃 Cómo Ejecutar

### Modo Desarrollo (Local)

```bash
# 1. Activar entorno virtual
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# 2. Iniciar Redis (si no está corriendo)
redis-server

# 3. Iniciar aplicación
python app.py

# O con auto-reload:
FLASK_DEBUG=1 python app.py

# O con Gunicorn (más realista):
gunicorn --bind 0.0.0.0:5000 --workers 4 --threads 2 --reload app:app
```

### Modo Producción (Docker)

```bash
# Iniciar todos los servicios
docker-compose up -d

# Verificar que todo esté corriendo
docker-compose ps

# Ver logs en tiempo real
docker-compose logs -f

# Detener servicios
docker-compose down
```

### Ejecutar Tareas en Background (Celery)

```bash
# Desarrollo (local)
celery -A celery_app worker --loglevel=info --concurrency=4

# Con beat para tareas programadas
celery -A celery_app worker --beat --loglevel=info

# Producción (Docker)
# Ya está configurado en docker-compose.yml
```

---

## 📁 Estructura del Proyecto

```
obyra/
├── app.py                      # Aplicación Flask principal
├── extensions.py               # Extensiones de Flask (db, login, etc.)
├── requirements.txt            # Dependencias Python
├── .env                        # Variables de entorno (NO commitear)
├── .env.example                # Ejemplo de variables
│
├── models/                     # Modelos SQLAlchemy
│   ├── __init__.py
│   ├── core.py                 # Usuario, Organización, RBAC
│   ├── projects.py             # Obras, Etapas, Tareas
│   ├── budgets.py              # Presupuestos
│   ├── inventory.py            # Inventario
│   ├── marketplace.py          # Marketplace
│   └── ...
│
├── services/                   # Lógica de negocio
│   ├── base.py                 # Clase base de servicios
│   ├── user_service.py         # Gestión de usuarios
│   ├── project_service.py      # Gestión de obras
│   ├── budget_service.py       # Gestión de presupuestos
│   ├── inventory_service.py    # Gestión de inventario
│   └── ...
│
├── templates/                  # Templates Jinja2
│   ├── base.html               # Template base
│   ├── auth/                   # Autenticación
│   ├── obras/                  # Obras
│   ├── presupuestos/           # Presupuestos
│   ├── reportes/               # Dashboards y reportes
│   └── ...
│
├── static/                     # Archivos estáticos
│   ├── css/
│   ├── js/
│   └── images/
│
├── migrations/                 # Migraciones de Alembic
│   └── versions/
│
├── config/                     # Configuraciones
│   ├── cache_config.py         # Redis caching
│   └── rate_limiter_config.py # Rate limiting
│
├── middleware/                 # Middleware de Flask
│   └── request_timing.py       # Métricas de performance
│
├── scripts/                    # Scripts utilitarios
│   ├── monitor_concurrency.py  # Monitor de recursos
│   └── verify_security_improvements.py
│
├── tests/                      # Tests
│   ├── conftest.py
│   ├── test_auth.py
│   └── ...
│
├── docker-compose.yml          # Producción
├── docker-compose.dev.yml      # Desarrollo
├── Dockerfile                  # Imagen de Docker
├── nginx/                      # Configuración Nginx
│   ├── nginx.conf
│   └── conf.d/
│
└── docs/                       # Documentación
    ├── SECURITY_IMPROVEMENTS.md
    ├── CONCURRENCY_ANALYSIS.md
    ├── MIGRATIONS_GUIDE.md
    └── ...
```

---

## 🛠️ Scripts Útiles

### Verificación de Seguridad

```bash
# Verificar mejoras de seguridad implementadas
python scripts/verify_security_improvements.py
```

### Monitor de Concurrencia

```bash
# Monitorear recursos en tiempo real (CPU, RAM, DB, Redis, Gunicorn)
python scripts/monitor_concurrency.py
```

### Migraciones

```bash
# Ver estado de migraciones
python -m flask db current

# Crear nueva migración
python -m flask db migrate -m "Descripción del cambio"

# Aplicar migraciones
python -m flask db upgrade

# Revertir última migración
python -m flask db downgrade
```

### Base de Datos

```bash
# Backup de base de datos
pg_dump -U obyra obyra_dev > backup_$(date +%Y%m%d).sql

# Restaurar backup
psql -U obyra -d obyra_dev < backup_20250101.sql

# Conectar a base de datos
psql -U obyra -d obyra_dev

# Ver tablas
psql -U obyra -d obyra_dev -c "\dt"
```

### Redis

```bash
# Conectar a Redis CLI
redis-cli

# Verificar keys
redis-cli KEYS "*"

# Limpiar cache
redis-cli FLUSHDB

# Monitorear comandos
redis-cli MONITOR
```

---

## 🐛 Troubleshooting

### Error: "No module named 'psycopg'"

**Causa**: psycopg (driver de PostgreSQL) requiere compilación.

**Solución**:

```bash
# Linux/macOS
pip install psycopg[binary]

# Windows
pip install psycopg-binary
```

### Error: "cairo" o "WeasyPrint" no se instala

**Causa**: WeasyPrint (para PDFs) requiere librerías del sistema.

**Solución**:

<details>
<summary><b>🐧 Linux</b></summary>

```bash
sudo apt install libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev
pip install weasyprint
```
</details>

<details>
<summary><b>🍎 macOS</b></summary>

```bash
brew install cairo pango gdk-pixbuf libffi
pip install weasyprint
```
</details>

<details>
<summary><b>🪟 Windows</b></summary>

1. Descargar GTK+ runtime desde: https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer
2. Instalar con opciones por defecto
3. `pip install weasyprint`
</details>

### Error: "FATAL: password authentication failed"

**Causa**: Credenciales incorrectas de PostgreSQL.

**Solución**:

1. Verificar que el usuario existe:
   ```bash
   sudo -u postgres psql -c "\du"
   ```

2. Recrear usuario:
   ```bash
   sudo -u postgres psql -c "DROP USER IF EXISTS obyra;"
   sudo -u postgres psql -c "CREATE USER obyra WITH PASSWORD 'obyra_dev_password';"
   sudo -u postgres psql -c "ALTER USER obyra CREATEDB;"
   ```

3. Verificar DATABASE_URL en `.env`

### Error: "Redis connection refused"

**Causa**: Redis no está corriendo.

**Solución**:

```bash
# Verificar si Redis está corriendo
redis-cli ping

# Si no responde, iniciar Redis:
# Linux
sudo systemctl start redis

# macOS
brew services start redis

# Windows
# Ejecutar redis-server.exe
```

### Error: Rate limiting no funciona

**Causa**: Redis no está configurado correctamente.

**Solución**:

1. Verificar que `RATE_LIMITER_STORAGE` está en `.env`:
   ```env
   RATE_LIMITER_STORAGE=redis://localhost:6379/1
   ```

2. Verificar que Redis está accesible:
   ```bash
   redis-cli -h localhost -p 6379 ping
   ```

3. Revisar logs de la aplicación para errores

### Aplicación muy lenta

**Diagnóstico**:

```bash
# 1. Verificar uso de CPU/RAM
python scripts/monitor_concurrency.py

# 2. Ver queries lentas en PostgreSQL
psql -U obyra -d obyra_dev <<EOF
SELECT query, calls, mean_exec_time, max_exec_time
FROM pg_stat_statements
WHERE mean_exec_time > 100
ORDER BY mean_exec_time DESC
LIMIT 20;
EOF

# 3. Verificar que Redis está funcionando
redis-cli INFO stats

# 4. Ver logs de errores
tail -f logs/errors.log
```

**Soluciones**:
- Ver [CONCURRENCY_ANALYSIS.md](CONCURRENCY_ANALYSIS.md) para optimizaciones
- Aumentar workers de Gunicorn
- Verificar que caching está habilitado
- Agregar índices a queries lentas

### No puedo hacer login

**Causas comunes**:

1. **Super admin no configurado**:
   ```bash
   python configurar_admin.py
   ```

2. **Password incorrecta**:
   ```bash
   # Resetear password del usuario
   python -c "from app import app, db; from models import Usuario; from werkzeug.security import generate_password_hash; \
   with app.app_context(): \
       u = Usuario.query.filter_by(email='admin@obyra.com').first(); \
       u.password_hash = generate_password_hash('nueva_password'); \
       db.session.commit(); \
       print('Password reseteada')"
   ```

3. **Rate limiting bloqueado**:
   ```bash
   # Limpiar rate limits de Redis
   redis-cli DEL "LIMITER:*"
   ```

### Docker: Contenedores no inician

```bash
# Ver logs de error
docker-compose logs

# Verificar que puertos no están ocupados
sudo lsof -i :5432  # PostgreSQL
sudo lsof -i :6379  # Redis
sudo lsof -i :5000  # App

# Limpiar todo y reiniciar
docker-compose down -v
docker-compose up -d --build
```

---

## 📚 Documentación Adicional

### Guías Técnicas
- [SECURITY_IMPROVEMENTS.md](SECURITY_IMPROVEMENTS.md) - Mejoras de seguridad implementadas
- [CONCURRENCY_ANALYSIS.md](CONCURRENCY_ANALYSIS.md) - Análisis de capacidad y escalamiento
- [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) - Reporte de verificación de seguridad
- [URGENT_FIXES_SUMMARY.md](URGENT_FIXES_SUMMARY.md) - Resumen de correcciones críticas

### Guías de Operación
- [CACHING_GUIDE.md](CACHING_GUIDE.md) - Sistema de caching con Redis
- [MIGRATIONS_GUIDE.md](MIGRATIONS_GUIDE.md) - Guía de migraciones de base de datos
- [LOGGING_IMPLEMENTATION.md](LOGGING_IMPLEMENTATION.md) - Sistema de logging

### Guías de Desarrollo
- [SERVICES_GUIDE.md](SERVICES_GUIDE.md) - Arquitectura de servicios
- [LOCAL_DEV_SETUP.md](LOCAL_DEV_SETUP.md) - Setup de desarrollo local

---

## 🤝 Contribuir

### Setup para Desarrollo

1. Fork el repositorio
2. Crear rama feature: `git checkout -b feature/nueva-funcionalidad`
3. Instalar pre-commit hooks (opcional):
   ```bash
   pip install pre-commit
   pre-commit install
   ```
4. Hacer cambios y commit
5. Push a tu fork: `git push origin feature/nueva-funcionalidad`
6. Crear Pull Request

### Ejecutar Tests

```bash
# Instalar dependencias de testing
pip install pytest pytest-cov

# Ejecutar todos los tests
pytest

# Con coverage
pytest --cov=. --cov-report=html

# Solo tests unitarios
pytest -m unit

# Solo tests de integración
pytest -m integration
```

---

## 📝 Notas de Versión

### Versión Actual (Noviembre 2025)

#### ✅ Mejoras de Seguridad
- Rate limiting implementado en 13+ endpoints críticos
- Eliminadas credenciales hardcodeadas
- Logging mejorado con stack traces completos
- Sistema de super admin basado en base de datos

#### ⚡ Mejoras de Performance
- Soporte para 200-400 usuarios concurrentes (configuración actual)
- Caching con Redis
- Índices optimizados en PostgreSQL
- Compresión gzip en Nginx

#### 🐛 Correcciones
- Migración completa a PostgreSQL 16
- Fixes en sistema de membresías
- Correcciones en wizard de presupuestos

---

## 📞 Soporte

Para problemas, preguntas o sugerencias:

1. **Revisar**: [Troubleshooting](#-troubleshooting) en este README
2. **Logs**: Revisar `logs/app.log` y `logs/errors.log`
3. **Documentación**: Ver carpeta `docs/` para guías detalladas
4. **Issues**: Reportar en el repositorio de GitHub

---

## ⚖️ Licencia

Este proyecto es propietario. Todos los derechos reservados.

---

## 🙏 Agradecimientos

Desarrollado con:
- [Flask](https://flask.palletsprojects.com/)
- [PostgreSQL](https://www.postgresql.org/)
- [Redis](https://redis.io/)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [Celery](https://docs.celeryq.dev/)

---

**Última actualización**: 2 de Noviembre de 2025
**Versión**: 2.0
