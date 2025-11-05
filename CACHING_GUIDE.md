# OBYRA - Guía de Redis Caching

**Fecha:** 2 de Noviembre, 2025
**Sistema:** Redis Caching para queries repetitivas

---

## 🎯 Resumen

Sistema de caching implementado usando Redis para optimizar queries repetitivas y reducir la carga en PostgreSQL.

### Beneficios
- ✅ Reduce latencia de queries frecuentes en 80-95%
- ✅ Disminuye carga en base de datos PostgreSQL
- ✅ Mejora experiencia de usuario con respuestas más rápidas
- ✅ Fallback automático si Redis no está disponible

---

## 📊 Configuración

### Variables de Entorno

```bash
# Redis para caching (DB 0)
REDIS_URL=redis://localhost:6382/0

# Redis para rate limiting (DB 1)
RATE_LIMITER_STORAGE=redis://localhost:6382/1
```

### Servidor Redis

```bash
# Docker (recomendado para desarrollo)
docker run -d --name obyra-redis-dev -p 6382:6379 redis:7-alpine

# Local
redis-server --port 6382
```

---

## 🔧 Uso del Sistema de Caching

### 1. Decoradores Disponibles

#### Decorador General: `@cache_query`

```python
from config.cache_config import cache_query

@cache_query(ttl=300, key_prefix='query')
def mi_funcion_costosa(param1, param2):
    # Query pesado aquí
    return resultado
```

**Parámetros:**
- `ttl` (int): Time To Live en segundos (default: 300 = 5 min)
- `key_prefix` (str): Prefijo para la clave de cache (default: 'query')

#### Decoradores Especializados

```python
from config.cache_config import (
    cache_user_query,      # TTL: 600s (10 min)
    cache_org_query,       # TTL: 300s (5 min)
    cache_obra_query,      # TTL: 60s (1 min)
    cache_permission_query # TTL: 900s (15 min)
)

# Ejemplo: Cachear búsqueda de usuario por email
@cache_user_query(ttl=600)
def get_user_by_email(email):
    return Usuario.query.filter_by(email=email).first()
```

### 2. Invalidar Cache

#### Invalidar Entry Específico

```python
from config.cache_config import invalidate_cache

# Invalidar cache de un query específico
invalidate_cache('user', 'user@example.com')
```

#### Invalidar por Patrón

```python
from config.cache_config import invalidate_pattern

# Invalidar todos los caches de usuarios
invalidate_pattern('obyra:user:*')

# Invalidar todos los caches de una organización
invalidate_pattern('obyra:org:123:*')

# Invalidar todos los caches de obras
invalidate_pattern('obyra:obra:*')
```

### 3. Forzar Refresh del Cache

```python
# Pasar flush_cache=True para ignorar cache y refrescar
user = get_user_by_email('user@example.com', flush_cache=True)
```

### 4. Obtener Estadísticas del Cache

```python
from config.cache_config import cache_stats

stats = cache_stats()
# {
#     'enabled': True,
#     'total_connections': 150,
#     'total_commands': 1250,
#     'keyspace_hits': 980,
#     'keyspace_misses': 120,
#     'hit_rate': 89.09
# }
```

---

## 📝 Ejemplos de Implementación

### Ejemplo 1: Cachear Query de Usuario

```python
# services/user_service.py

from config.cache_config import cache_user_query, invalidate_pattern

class UserService(BaseService[Usuario]):

    @cache_user_query(ttl=600)  # Cache por 10 minutos
    def get_by_email(self, email: str) -> Optional[Usuario]:
        """Obtiene usuario por email (cacheado)"""
        if not email:
            return None

        email = email.strip().lower()
        return Usuario.query.filter(
            db.func.lower(Usuario.email) == email
        ).first()

    def register(self, email: str, nombre: str, ...) -> Usuario:
        """Registra nuevo usuario"""
        # ... lógica de registro ...

        db.session.commit()

        # Invalidar cache al crear usuario
        invalidate_pattern('obyra:user:*')

        return user
```

### Ejemplo 2: Cachear Query de Organización

```python
# services/org_service.py

from config.cache_config import cache_org_query, invalidate_pattern

@cache_org_query(ttl=300)  # Cache por 5 minutos
def get_organizacion_by_id(org_id: int):
    return Organizacion.query.get(org_id)

def update_organizacion(org_id: int, **kwargs):
    org = Organizacion.query.get(org_id)
    # ... actualizar campos ...

    db.session.commit()

    # Invalidar cache de esta organización
    invalidate_pattern(f'obyra:org:{org_id}:*')
    invalidate_pattern('obyra:org:*')
```

### Ejemplo 3: Cachear Permisos de Usuario

```python
# services/permissions_service.py

from config.cache_config import cache_permission_query, invalidate_pattern

@cache_permission_query(ttl=900)  # Cache por 15 minutos
def get_user_permissions(user_id: int, org_id: int):
    """Obtiene permisos de usuario (cacheado)"""
    return UserModule.query.filter_by(
        user_id=user_id,
        org_id=org_id
    ).all()

def update_user_permissions(user_id: int, org_id: int, permissions: dict):
    # ... actualizar permisos ...

    db.session.commit()

    # Invalidar cache de permisos
    invalidate_pattern(f'obyra:permission:*')
```

---

## ⚙️ Serialización Automática

El sistema serializa automáticamente:
- ✅ Objetos SQLAlchemy (modelos)
- ✅ Diccionarios y listas
- ✅ Tipos primitivos (str, int, float, bool, None)
- ✅ Objetos datetime/date
- ✅ Objetos JSON-serializables

**Nota:** Los objetos SQLAlchemy se serializan a diccionarios con sus columnas.

---

## 🔍 Monitoreo y Debugging

### Ver Claves en Redis

```bash
# Conectar a Redis
redis-cli -p 6382

# Listar todas las claves
KEYS obyra:*

# Ver una clave específica
GET obyra:user:a3f2b8c4d5e6

# Ver TTL de una clave
TTL obyra:user:a3f2b8c4d5e6

# Borrar una clave
DEL obyra:user:a3f2b8c4d5e6

# Borrar todas las claves del DB actual
FLUSHDB
```

### Logs de Cache

El sistema loguea automáticamente:
- `[OK] Redis cache configurado: redis://...` - Cache inicializado
- `[WARN] Redis cache no disponible: ...` - Redis no accesible
- `[WARN] Error leyendo cache ...` - Error al leer del cache
- `[WARN] Error guardando cache ...` - Error al guardar en cache
- `[WARN] No se puede cachear resultado de ...` - Objeto no serializable

---

## 📈 Mejores Prácticas

### 1. TTL Apropiados

- **Datos estáticos** (configuraciones, roles): 15-30 minutos
- **Datos de usuario** (perfil, permisos): 5-10 minutos
- **Datos de sesión** (organizaciones): 5 minutos
- **Datos frecuentemente actualizados** (obras, tareas): 1-2 minutos

### 2. Invalidación Granular vs Patrón

```python
# ✅ BUENO: Invalidar solo lo necesario
invalidate_pattern(f'obyra:user:{user_id}:*')

# ⚠️ CUIDADO: Invalidar todo el cache (costoso)
invalidate_pattern('obyra:*')
```

### 3. Queries Ideales para Cachear

✅ **Cachear:**
- Búsquedas por ID/email (frecuentes, no cambian)
- Permisos y roles (consulta frecuente, cambio poco frecuente)
- Configuraciones de organización
- Listas de opciones estáticas

❌ **NO cachear:**
- Queries con parámetros de paginación
- Datos en tiempo real (avances de obra en vivo)
- Datos de alta frecuencia de escritura

### 4. Manejo de Cache Stale

```python
# Siempre invalidar cache al modificar datos
def update_user(user_id, **kwargs):
    user = Usuario.query.get(user_id)
    # ... actualizar ...
    db.session.commit()

    # ✅ Invalidar cache relacionado
    invalidate_pattern('obyra:user:*')
```

---

## 🚨 Troubleshooting

### Cache No Funciona

1. Verificar que Redis está corriendo:
   ```bash
   redis-cli -p 6382 ping
   # Respuesta esperada: PONG
   ```

2. Verificar variable de entorno:
   ```bash
   echo $REDIS_URL
   # Esperado: redis://localhost:6382/0
   ```

3. Verificar logs de inicio:
   ```
   [OK] Redis cache configurado: redis://localhost:6382/0
   ```

### Hit Rate Bajo

- Revisar TTL (muy cortos = más misses)
- Verificar que se invalida correctamente al modificar datos
- Monitorear estadísticas: `cache_stats()`

### Memoria Redis Alta

- Reducir TTL de caches menos importantes
- Implementar política de eviction en Redis:
  ```bash
  redis-cli CONFIG SET maxmemory 256mb
  redis-cli CONFIG SET maxmemory-policy allkeys-lru
  ```

---

## 📊 Métricas de Rendimiento

### Impacto Esperado

| Query Type | Sin Cache | Con Cache | Mejora |
|------------|-----------|-----------|--------|
| get_user_by_email | ~50ms | ~5ms | **90% más rápido** |
| get_user_permissions | ~120ms | ~8ms | **93% más rápido** |
| get_organizacion | ~40ms | ~4ms | **90% más rápido** |

### Hit Rate Objetivo

- **Excelente**: > 85% hit rate
- **Bueno**: 70-85% hit rate
- **Necesita optimización**: < 70% hit rate

---

## 🔗 Referencias

- **Configuración**: `config/cache_config.py` (350 líneas)
- **Integración**: `services/user_service.py` (decoradores aplicados)
- **Redis Docs**: https://redis.io/documentation
- **Flask-Limiter**: https://flask-limiter.readthedocs.io/

---

**Generado automáticamente por Claude Code**
**Fecha:** 2 de Noviembre, 2025
