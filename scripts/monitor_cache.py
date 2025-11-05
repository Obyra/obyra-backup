#!/usr/bin/env python3
"""
Script de Monitoreo de Cache Redis
===================================
Muestra estadísticas de hit rate del cache Redis y métricas de performance.

Uso:
    python scripts/monitor_cache.py
    python scripts/monitor_cache.py --watch  # Actualiza cada 5 segundos
"""

import os
import sys
import time
from pathlib import Path

# Agregar el directorio raíz al path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

try:
    import redis
except ImportError:
    print("ERROR: redis package no instalado")
    print("Instalar con: pip install redis")
    sys.exit(1)


def get_redis_client():
    """Obtiene cliente Redis"""
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6382/0')
    try:
        client = redis.from_url(redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception as e:
        print(f"ERROR: No se pudo conectar a Redis: {e}")
        sys.exit(1)


def get_cache_stats(client):
    """Obtiene estadísticas del cache"""
    try:
        info = client.info('stats')
        keyspace = client.info('keyspace')

        hits = info.get('keyspace_hits', 0)
        misses = info.get('keyspace_misses', 0)
        total = hits + misses

        hit_rate = (hits / total * 100) if total > 0 else 0

        # Contar claves por prefijo
        obyra_keys = len(list(client.scan_iter(match='obyra:*', count=100)))

        db0_info = keyspace.get('db0', {})
        if isinstance(db0_info, dict):
            total_keys = db0_info.get('keys', 0)
        else:
            # Parse string format "keys=X,expires=Y"
            total_keys = 0
            if db0_info:
                parts = db0_info.split(',')
                for part in parts:
                    if part.startswith('keys='):
                        total_keys = int(part.split('=')[1])

        return {
            'hits': hits,
            'misses': misses,
            'total_requests': total,
            'hit_rate': hit_rate,
            'total_keys': total_keys,
            'obyra_keys': obyra_keys,
            'commands_processed': info.get('total_commands_processed', 0),
            'connections_received': info.get('total_connections_received', 0),
        }
    except Exception as e:
        print(f"ERROR obteniendo estadísticas: {e}")
        return None


def get_key_stats(client):
    """Obtiene estadísticas por tipo de clave"""
    patterns = {
        'users': 'obyra:user:*',
        'orgs': 'obyra:org:*',
        'obras': 'obyra:obra:*',
        'permissions': 'obyra:permission:*',
        'other': 'obyra:*'
    }

    stats = {}
    for name, pattern in patterns.items():
        try:
            keys = list(client.scan_iter(match=pattern, count=100))
            stats[name] = len(keys)
        except:
            stats[name] = 0

    return stats


def print_stats(stats, key_stats):
    """Imprime estadísticas en formato legible"""
    print("\n" + "="*60)
    print("  OBYRA - Estadísticas de Redis Cache")
    print("="*60)

    print(f"\n📊 MÉTRICAS GENERALES")
    print(f"  Total Requests:     {stats['total_requests']:,}")
    print(f"  Cache Hits:         {stats['hits']:,}")
    print(f"  Cache Misses:       {stats['misses']:,}")
    print(f"  Hit Rate:           {stats['hit_rate']:.2f}%")

    # Indicador de performance
    if stats['hit_rate'] >= 85:
        indicator = "🟢 Excelente"
    elif stats['hit_rate'] >= 70:
        indicator = "🟡 Bueno"
    else:
        indicator = "🔴 Necesita optimización"

    print(f"  Status:             {indicator}")

    print(f"\n🔑 CLAVES EN REDIS")
    print(f"  Total Claves:       {stats['total_keys']:,}")
    print(f"  Claves OBYRA:       {stats['obyra_keys']:,}")

    print(f"\n📦 DISTRIBUCIÓN POR TIPO")
    for key_type, count in sorted(key_stats.items(), key=lambda x: x[1], reverse=True):
        if key_type != 'other':
            print(f"  {key_type.capitalize():15} {count:,}")

    print(f"\n🌐 CONEXIONES")
    print(f"  Total Conexiones:   {stats['connections_received']:,}")
    print(f"  Total Comandos:     {stats['commands_processed']:,}")

    print("\n" + "="*60)


def main():
    """Función principal"""
    watch = '--watch' in sys.argv

    client = get_redis_client()
    print(f"✓ Conectado a Redis: {os.getenv('REDIS_URL', 'redis://localhost:6382/0')}")

    try:
        while True:
            stats = get_cache_stats(client)
            if not stats:
                break

            key_stats = get_key_stats(client)
            print_stats(stats, key_stats)

            if not watch:
                break

            print("\nActualizando cada 5 segundos... (Ctrl+C para salir)")
            time.sleep(5)

    except KeyboardInterrupt:
        print("\n\nMonitoreo detenido por el usuario")
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
