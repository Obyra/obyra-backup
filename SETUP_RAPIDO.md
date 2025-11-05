# 🚀 OBYRA - Setup Rápido (Nueva Instalación)

## 📋 Resumen

Este documento te guía para configurar OBYRA desde cero en una nueva computadora.

## ✅ Prerequisitos

- Docker & Docker Compose instalados
- Puertos disponibles: 5436 (PostgreSQL), 6381 (Redis), 5003 (App), 8080 (Nginx)

## 🎯 Pasos de Instalación

### 1. Clonar o copiar el proyecto

```bash
cd /ruta/donde/quieras/obyra
# Si tienes el código, solo cópialo aquí
```

### 2. Configurar variables de entorno

```bash
# Ya está configurado en el .env actual:
# - PostgreSQL en puerto 5436
# - Redis en puerto 6381
# - Credenciales: obyra / obyra_dev_password
```

### 3. Levantar los contenedores

```bash
# Construir imágenes
docker-compose build

# Iniciar todos los servicios
docker-compose up -d

# Verificar que estén corriendo
docker-compose ps
```

### 4. Inicializar la base de datos

```bash
# Entrar al contenedor de la app
docker exec -it obyra-app bash

# Dentro del contenedor, ejecutar:
python << 'EOF'
from app import app, db
from models import Usuario, Organizacion, RoleModule
from werkzeug.security import generate_password_hash
from datetime import datetime

with app.app_context():
    # Crear tablas
    db.create_all()

    # Crear organización
    org = Organizacion(nombre="OBYRA", fecha_creacion=datetime.utcnow(), activa=True)
    db.session.add(org)
    db.session.commit()

    # Crear usuario admin
    admin = Usuario(
        email="admin@obyra.com",
        password_hash=generate_password_hash("Obyra2025!"),
        nombre="Super",
        apellido="Admin",
        rol="admin",
        role="admin",
        is_super_admin=True,
        activo=True,
        organizacion_id=org.id,
        primary_org_id=org.id,
        fecha_creacion=datetime.utcnow(),
        auth_provider='local'
    )
    db.session.add(admin)
    db.session.commit()

    print(f"✅ Base de datos inicializada!")
    print(f"✅ Usuario admin creado: admin@obyra.com / Obyra2025!")
EOF

# Salir del contenedor
exit
```

### 5. Acceder a la aplicación

Abre tu navegador en:
- **Directo**: http://localhost:5003
- **Vía Nginx**: http://localhost:8080

**Credenciales de acceso:**
- Email: `admin@obyra.com`
- Password: `Obyra2025!`

## 🔧 Comandos Útiles

```bash
# Ver logs de la aplicación
docker logs -f obyra-app

# Reiniciar servicios
docker-compose restart

# Detener todo
docker-compose down

# Detener y eliminar volúmenes (⚠️  Borra la BD)
docker-compose down -v

# Ver estado de contenedores
docker-compose ps

# Entrar a PostgreSQL
docker exec -it obyra-postgres psql -U obyra -d obyra_dev
```

## 🐛 Troubleshooting

### Problema: Puerto ocupado
```bash
# Cambiar puertos en docker-compose.yml
# Por ejemplo, cambiar 5436:5432 a 5437:5432
```

### Problema: No se puede conectar a la BD
```bash
# Verificar que PostgreSQL esté corriendo
docker-compose ps | grep postgres

# Ver logs de PostgreSQL
docker logs obyra-postgres
```

### Problema: Error 500 en la aplicación
```bash
# Ver logs para identificar el error
docker logs obyra-app | tail -50

# Verificar que las tablas existan
docker exec obyra-postgres psql -U obyra -d obyra_dev -c "\dt"
```

## 📁 Estructura de Archivos Importante

```
obyra-backup/
├── docker-compose.yml      # Configuración de contenedores
├── Dockerfile               # Imagen de la aplicación
├── .env                     # Variables de entorno
├── app.py                   # Aplicación principal
├── models/                  # Modelos de base de datos
├── utils/                   # Utilidades (creado con fixes)
│   ├── __init__.py
│   ├── security_logger.py
│   └── pagination.py
├── scripts/
│   ├── init_database.py    # Script de inicialización
│   └── monitor_concurrency.py
└── migrations/              # Migraciones de Alembic
```

## ✨ Mejoras de Seguridad Implementadas

- ✅ Rate limiting en 13+ endpoints críticos
- ✅ Logging de seguridad mejorado
- ✅ Super admin manejado por BD (no hardcoded)
- ✅ Imports arreglados (utils.security_logger, Pagination)
- ✅ Constraint duplicado arreglado (unique_tarea_miembro/unique_tarea_user)

## 📞 Soporte

Si encuentras problemas:
1. Revisa los logs: `docker logs obyra-app`
2. Verifica la conexión: `docker exec obyra-postgres pg_isready`
3. Consulta `VERIFICATION_REPORT.md` para troubleshooting

---
**Última actualización**: 2 de Noviembre de 2025
