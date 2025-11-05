# Mapeo de Puertos - OBYRA Docker

Este documento lista todos los puertos configurados para los servicios Docker de OBYRA.

## 🔴 Puertos Ocupados en el Sistema

Los siguientes puertos **NO están disponibles** porque ya están en uso:

- **5000**: Flask app local (ControlCe)
- **5432**: PostgreSQL (Docker existente)
- **5435**: PostgreSQL secundario (Docker existente)
- **6379**: Redis (Docker existente)
- **6380**: Redis secundario (Docker existente)

## 🟢 Puertos Configurados para OBYRA

### Producción (`docker-compose.yml`)

| Servicio | Puerto Interno | Puerto Externo | URL de Acceso |
|----------|---------------|----------------|---------------|
| **Flask App** | 5000 | **5003** | http://localhost:5003 |
| **PostgreSQL** | 5432 | **5436** | localhost:5436 |
| **Redis** | 6379 | **6381** | localhost:6381 |
| **Nginx HTTP** | 80 | **8080** | http://localhost:8080 |
| **Nginx HTTPS** | 443 | **8443** | https://localhost:8443 |

### Desarrollo (`docker-compose.dev.yml`)

| Servicio | Puerto Interno | Puerto Externo | URL de Acceso |
|----------|---------------|----------------|---------------|
| **Flask App (Dev)** | 5000 | **5002** | http://localhost:5002 |
| **PostgreSQL (Dev)** | 5432 | **5434** | localhost:5434 |
| **Redis (Dev)** | 6379 | **6382** | localhost:6382 |
| **pgAdmin** | 80 | **5051** | http://localhost:5051 |
| **Redis Commander** | 8081 | **8082** | http://localhost:8082 |

## 📝 Notas Importantes

### Acceso Principal

- **Desarrollo**: Accede a la app en **http://localhost:5002**
- **Producción**: Accede vía Nginx en **http://localhost:8080**

### Herramientas de Administración (Solo Dev)

Para iniciar las herramientas de admin (pgAdmin y Redis Commander):

```bash
docker-compose -f docker-compose.dev.yml --profile tools up -d
```

- **pgAdmin**: http://localhost:5051
  - Usuario: admin@obyra.local
  - Password: admin
  - Conectar a PostgreSQL: host=postgres, port=5432, usuario=obyra, password=obyra_dev_password

- **Redis Commander**: http://localhost:8082
  - Automáticamente conectado al Redis interno

### Conexiones de Base de Datos

#### Desde fuera de Docker (host):

```bash
# PostgreSQL Producción
psql -h localhost -p 5436 -U obyra -d obyra_prod

# PostgreSQL Desarrollo
psql -h localhost -p 5434 -U obyra -d obyra_dev

# Redis Producción
redis-cli -h localhost -p 6381

# Redis Desarrollo
redis-cli -h localhost -p 6382
```

#### Desde dentro de Docker (containers):

Los servicios se comunican internamente usando los nombres de servicio y puertos internos:

```yaml
# Ejemplo de conexión interna
DATABASE_URL: postgresql+psycopg://obyra:password@postgres:5432/obyra_prod
REDIS_URL: redis://redis:6379/0
```

## 🔧 Cambiar Puertos

Si necesitas cambiar los puertos externos, edita los archivos:

1. **Producción**: `docker-compose.yml`
2. **Desarrollo**: `docker-compose.dev.yml`

Busca la sección `ports:` de cada servicio y modifica el puerto externo (izquierdo):

```yaml
ports:
  - "PUERTO_EXTERNO:PUERTO_INTERNO"
```

Después de cambiar puertos:

```bash
# Recrear los servicios
docker-compose down
docker-compose up -d
```

## 🚨 Conflictos de Puertos

Si obtienes un error como:

```
Error: bind: address already in use
```

Significa que el puerto externo ya está ocupado. Verifica qué proceso lo está usando:

```bash
# macOS/Linux
lsof -nP -iTCP:PUERTO -sTCP:LISTEN

# Ver todos los puertos ocupados
lsof -nP -iTCP -sTCP:LISTEN | grep -E ":(5000|5432|6379)"
```

Luego cambia el puerto en el docker-compose correspondiente.

## 📊 Resumen Visual

```
Sistema Host (macOS)
├─ Puerto 5000 ─── App Flask Local (ocupado) ❌
├─ Puerto 5001 ─── node (ocupado) ❌
├─ Puerto 5002 ─── OBYRA Desarrollo (Flask) ✅
├─ Puerto 5003 ─── OBYRA Producción (Flask) ✅
├─ Puerto 5432 ─── PostgreSQL existente (ocupado) ❌
├─ Puerto 5433 ─── Docker existente (ocupado) ❌
├─ Puerto 5434 ─── OBYRA Desarrollo (PostgreSQL) ✅
├─ Puerto 5436 ─── OBYRA Producción (PostgreSQL) ✅
├─ Puerto 5051 ─── pgAdmin (Dev Tools) ✅
├─ Puerto 6379 ─── Redis existente (ocupado) ❌
├─ Puerto 6380 ─── Redis existente (ocupado) ❌
├─ Puerto 6381 ─── OBYRA Producción (Redis) ✅
├─ Puerto 6382 ─── OBYRA Desarrollo (Redis) ✅
├─ Puerto 8080 ─── OBYRA Nginx HTTP ✅
├─ Puerto 8082 ─── Redis Commander (Dev Tools) ✅
└─ Puerto 8443 ─── OBYRA Nginx HTTPS ✅
```

---

**Última actualización**: 2025-01-02
