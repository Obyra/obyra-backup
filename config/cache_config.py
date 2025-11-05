"""
Redis Cache Configuration for OBYRA
====================================
Proporciona decoradores y utilidades para cachear queries repetitivas usando Redis.

Uso:
    from config.cache_config import cache_query, invalidate_cache

    @cache_query(ttl=300, key_prefix='user')
    def get_user_by_email(email):
        return Usuario.query.filter_by(email=email).first()
"""

import os
import json
import functools
import hashlib
from typing import Any, Optional, Callable
from datetime import timedelta, datetime, date

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


def _serialize_value(value: Any) -> str:
    """
    Serializa un valor a JSON, manejando objetos SQLAlchemy.

    Args:
        value: Valor a serializar (puede ser modelo SQLAlchemy, dict, list, etc.)

    Returns:
        String JSON del valor serializado
    """
    def default_serializer(obj):
        """Serializer personalizado para objetos no-JSON"""
        # Manejar objetos SQLAlchemy
        if hasattr(obj, '__table__'):
            # Convertir modelo SQLAlchemy a dict
            return {
                c.name: getattr(obj, c.name)
                for c in obj.__table__.columns
            }
        # Manejar datetime
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        # Para otros objetos, convertir a string
        return str(obj)

    return json.dumps(value, default=default_serializer, ensure_ascii=False)


class CacheConfig:
    """Configuración centralizada del cache Redis"""

    def __init__(self):
        self.enabled = REDIS_AVAILABLE and os.getenv('REDIS_URL') is not None
        self.redis_client: Optional[redis.Redis] = None
        self.default_ttl = 300  # 5 minutos por defecto

        if self.enabled:
            try:
                redis_url = os.getenv('REDIS_URL', 'redis://localhost:6382/0')
                self.redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2
                )
                # Test connection
                self.redis_client.ping()
                print(f"[OK] Redis cache configurado: {redis_url}")
            except Exception as e:
                print(f"[WARN] Redis cache no disponible: {e}")
                self.enabled = False
                self.redis_client = None

    def get_client(self) -> Optional[redis.Redis]:
        """Retorna el cliente Redis si está disponible"""
        return self.redis_client if self.enabled else None

    def is_enabled(self) -> bool:
        """Verifica si el cache está habilitado y funcionando"""
        return self.enabled and self.redis_client is not None


# Instancia global del cache
_cache_config = CacheConfig()


def get_cache() -> CacheConfig:
    """Retorna la instancia global de configuración del cache"""
    return _cache_config


def _generate_cache_key(prefix: str, *args, **kwargs) -> str:
    """
    Genera una clave de cache única basada en los argumentos.

    Args:
        prefix: Prefijo para la clave (ej: 'user', 'org', 'obra')
        *args: Argumentos posicionales de la función
        **kwargs: Argumentos nombrados de la función

    Returns:
        Clave de cache en formato: prefix:hash
    """
    # Crear string único con todos los argumentos
    key_data = {
        'args': args,
        'kwargs': {k: v for k, v in sorted(kwargs.items()) if k != 'flush_cache'}
    }

    # Generar hash MD5 del JSON de los datos
    data_str = json.dumps(key_data, sort_keys=True, default=str)
    data_hash = hashlib.md5(data_str.encode()).hexdigest()[:12]

    return f"obyra:{prefix}:{data_hash}"


def cache_query(ttl: int = 300, key_prefix: str = 'query'):
    """
    Decorador para cachear resultados de queries en Redis.

    Args:
        ttl: Time to live en segundos (default: 300 = 5 minutos)
        key_prefix: Prefijo para la clave de cache

    Ejemplo:
        @cache_query(ttl=600, key_prefix='user_email')
        def get_user_by_email(email):
            return Usuario.query.filter_by(email=email).first()

    Notas:
        - Si Redis no está disponible, ejecuta la función normalmente sin cachear
        - Para forzar refrescar cache, pasar flush_cache=True como parámetro
        - Solo cachea objetos serializables a JSON (str, int, dict, list, None)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_cache()

            # Si cache no está habilitado, ejecutar función directamente
            if not cache.is_enabled():
                return func(*args, **kwargs)

            # Permitir forzar refresh del cache
            flush_cache = kwargs.pop('flush_cache', False)

            # Generar clave de cache
            cache_key = _generate_cache_key(key_prefix, *args, **kwargs)

            # Si no se fuerza flush, intentar obtener del cache
            if not flush_cache:
                try:
                    client = cache.get_client()
                    cached_value = client.get(cache_key)

                    if cached_value is not None:
                        # Cache hit
                        return json.loads(cached_value)
                except Exception as e:
                    # Si hay error al leer cache, continuar sin cachear
                    print(f"[WARN] Error leyendo cache {cache_key}: {e}")

            # Cache miss o flush - ejecutar función
            result = func(*args, **kwargs)

            # Intentar guardar en cache
            try:
                if result is not None:
                    client = cache.get_client()
                    serialized = _serialize_value(result)
                    client.setex(cache_key, ttl, serialized)
            except (TypeError, ValueError) as e:
                # Objeto no serializable, no cachear
                print(f"[WARN] No se puede cachear resultado de {func.__name__}: {e}")
            except Exception as e:
                # Otros errores de Redis, continuar sin cachear
                print(f"[WARN] Error guardando cache {cache_key}: {e}")

            return result

        return wrapper
    return decorator


def invalidate_cache(key_prefix: str, *args, **kwargs) -> bool:
    """
    Invalida una entrada específica del cache.

    Args:
        key_prefix: Prefijo de la clave a invalidar
        *args: Argumentos usados para generar la clave
        **kwargs: Argumentos nombrados usados para generar la clave

    Returns:
        True si se invalidó exitosamente, False en caso contrario

    Ejemplo:
        # Invalidar cache de get_user_by_email('user@example.com')
        invalidate_cache('user_email', 'user@example.com')
    """
    cache = get_cache()
    if not cache.is_enabled():
        return False

    try:
        cache_key = _generate_cache_key(key_prefix, *args, **kwargs)
        client = cache.get_client()
        return client.delete(cache_key) > 0
    except Exception as e:
        print(f"[WARN] Error invalidando cache: {e}")
        return False


def invalidate_pattern(pattern: str) -> int:
    """
    Invalida múltiples claves que coincidan con un patrón.

    Args:
        pattern: Patrón de búsqueda (ej: 'obyra:user:*', 'obyra:org:123:*')

    Returns:
        Número de claves eliminadas

    Ejemplo:
        # Invalidar todos los caches de usuarios
        invalidate_pattern('obyra:user:*')

        # Invalidar todos los caches de una organización específica
        invalidate_pattern('obyra:org:123:*')
    """
    cache = get_cache()
    if not cache.is_enabled():
        return 0

    try:
        client = cache.get_client()
        keys = list(client.scan_iter(match=pattern, count=100))

        if keys:
            return client.delete(*keys)
        return 0
    except Exception as e:
        print(f"[WARN] Error invalidando patrón {pattern}: {e}")
        return 0


def cache_stats() -> dict:
    """
    Retorna estadísticas del cache Redis.

    Returns:
        Diccionario con estadísticas del cache
    """
    cache = get_cache()
    if not cache.is_enabled():
        return {
            'enabled': False,
            'message': 'Redis cache no disponible'
        }

    try:
        client = cache.get_client()
        info = client.info('stats')

        return {
            'enabled': True,
            'total_connections': info.get('total_connections_received', 0),
            'total_commands': info.get('total_commands_processed', 0),
            'keyspace_hits': info.get('keyspace_hits', 0),
            'keyspace_misses': info.get('keyspace_misses', 0),
            'hit_rate': _calculate_hit_rate(
                info.get('keyspace_hits', 0),
                info.get('keyspace_misses', 0)
            )
        }
    except Exception as e:
        return {
            'enabled': False,
            'error': str(e)
        }


def _calculate_hit_rate(hits: int, misses: int) -> float:
    """Calcula el porcentaje de hit rate del cache"""
    total = hits + misses
    if total == 0:
        return 0.0
    return round((hits / total) * 100, 2)


# Decoradores especializados para casos comunes

def cache_user_query(ttl: int = 600):
    """Decorador especializado para queries de usuarios (10 min TTL)"""
    return cache_query(ttl=ttl, key_prefix='user')


def cache_org_query(ttl: int = 300):
    """Decorador especializado para queries de organizaciones (5 min TTL)"""
    return cache_query(ttl=ttl, key_prefix='org')


def cache_obra_query(ttl: int = 60):
    """Decorador especializado para queries de obras (1 min TTL)"""
    return cache_query(ttl=ttl, key_prefix='obra')


def cache_permission_query(ttl: int = 900):
    """Decorador especializado para queries de permisos (15 min TTL)"""
    return cache_query(ttl=ttl, key_prefix='permission')
