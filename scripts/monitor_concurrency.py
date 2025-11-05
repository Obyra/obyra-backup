#!/usr/bin/env python3
"""
Script para monitorear la concurrencia y uso de recursos del sistema OBYRA.
Muestra métricas en tiempo real de todos los componentes críticos.
"""

import os
import sys
import time
import psutil
from datetime import datetime
from typing import Dict, Any

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def clear_screen():
    """Limpiar la pantalla."""
    os.system('clear' if os.name == 'posix' else 'cls')


def get_system_metrics() -> Dict[str, Any]:
    """Obtener métricas del sistema."""
    cpu_percent = psutil.cpu_percent(interval=1, percpu=False)
    memory = psutil.virtual_memory()

    return {
        'cpu_percent': cpu_percent,
        'memory_percent': memory.percent,
        'memory_used_mb': memory.used / (1024 * 1024),
        'memory_total_mb': memory.total / (1024 * 1024),
    }


def get_postgres_metrics() -> Dict[str, Any]:
    """Obtener métricas de PostgreSQL."""
    try:
        from app import app, db
        from sqlalchemy import text

        with app.app_context():
            # Conexiones activas
            result = db.session.execute(text("""
                SELECT
                    count(*) as total_connections,
                    count(*) FILTER (WHERE state = 'active') as active_connections,
                    count(*) FILTER (WHERE state = 'idle') as idle_connections
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid != pg_backend_pid()
            """))

            row = result.fetchone()

            # Queries lentas (>1s)
            slow_queries = db.session.execute(text("""
                SELECT count(*)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND state = 'active'
                  AND now() - query_start > interval '1 second'
            """)).scalar()

            return {
                'total_connections': row[0] if row else 0,
                'active_connections': row[1] if row else 0,
                'idle_connections': row[2] if row else 0,
                'slow_queries': slow_queries or 0,
                'pool_size': 10,
                'max_overflow': 20,
                'max_total': 30,
            }
    except Exception as e:
        return {
            'error': str(e),
            'total_connections': 0,
            'active_connections': 0,
            'idle_connections': 0,
            'slow_queries': 0,
            'pool_size': 10,
            'max_overflow': 20,
            'max_total': 30,
        }


def get_redis_metrics() -> Dict[str, Any]:
    """Obtener métricas de Redis."""
    try:
        import redis

        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6382/0')
        r = redis.from_url(redis_url)

        info = r.info()

        return {
            'connected_clients': info.get('connected_clients', 0),
            'used_memory_mb': info.get('used_memory', 0) / (1024 * 1024),
            'max_memory_mb': info.get('maxmemory', 536870912) / (1024 * 1024),  # Default 512MB
            'keys_total': r.dbsize(),
            'ops_per_sec': info.get('instantaneous_ops_per_sec', 0),
            'hit_rate': info.get('keyspace_hits', 0) / max(info.get('keyspace_hits', 0) + info.get('keyspace_misses', 1), 1) * 100,
        }
    except Exception as e:
        return {
            'error': str(e),
            'connected_clients': 0,
            'used_memory_mb': 0,
            'max_memory_mb': 512,
            'keys_total': 0,
            'ops_per_sec': 0,
            'hit_rate': 0,
        }


def get_gunicorn_workers() -> int:
    """Contar workers de Gunicorn activos."""
    try:
        count = 0
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                if 'gunicorn' in proc.info['name'].lower():
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return count
    except Exception:
        return 0


def calculate_capacity(active_requests: int, workers: int, threads: int) -> Dict[str, Any]:
    """Calcular capacidad actual y usuarios estimados."""
    max_concurrent = workers * threads
    usage_percent = (active_requests / max_concurrent * 100) if max_concurrent > 0 else 0

    # Asumiendo request promedio de 300ms y 3 requests/min por usuario
    avg_request_time = 0.3  # segundos
    requests_per_user_min = 3

    if avg_request_time > 0:
        throughput = max_concurrent / avg_request_time
        estimated_users = (throughput * 60) / requests_per_user_min
    else:
        estimated_users = 0

    return {
        'max_concurrent': max_concurrent,
        'active_requests': active_requests,
        'usage_percent': usage_percent,
        'estimated_users': int(estimated_users),
    }


def get_color(percent: float) -> str:
    """Obtener código de color según porcentaje."""
    if percent < 50:
        return '\033[92m'  # Verde
    elif percent < 75:
        return '\033[93m'  # Amarillo
    else:
        return '\033[91m'  # Rojo


def reset_color() -> str:
    """Reset color."""
    return '\033[0m'


def format_bar(percent: float, width: int = 30) -> str:
    """Crear barra de progreso."""
    filled = int(width * percent / 100)
    bar = '█' * filled + '░' * (width - filled)
    color = get_color(percent)
    return f"{color}{bar}{reset_color()} {percent:.1f}%"


def display_metrics():
    """Mostrar todas las métricas en tiempo real."""
    clear_screen()

    print("╔═══════════════════════════════════════════════════════════════════╗")
    print("║        MONITOR DE CONCURRENCIA - SISTEMA OBYRA                   ║")
    print("╚═══════════════════════════════════════════════════════════════════╝")
    print(f"\n⏰ Actualizado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n" + "=" * 70)

    # Sistema
    print("\n📊 SISTEMA")
    print("-" * 70)
    system = get_system_metrics()
    print(f"CPU:    {format_bar(system['cpu_percent'])}")
    print(f"RAM:    {format_bar(system['memory_percent'])} "
          f"({system['memory_used_mb']:.0f}MB / {system['memory_total_mb']:.0f}MB)")

    # PostgreSQL
    print("\n🐘 POSTGRESQL")
    print("-" * 70)
    pg = get_postgres_metrics()

    if 'error' in pg:
        print(f"⚠️  Error: {pg['error']}")
    else:
        conn_percent = (pg['total_connections'] / pg['max_total'] * 100) if pg['max_total'] > 0 else 0
        print(f"Conexiones Totales:  {pg['total_connections']}/{pg['max_total']} "
              f"{format_bar(conn_percent, 20)}")
        print(f"  ├─ Activas:  {pg['active_connections']}")
        print(f"  ├─ Idle:     {pg['idle_connections']}")
        print(f"  └─ Lentas (>1s): {pg['slow_queries']}")

        if pg['slow_queries'] > 0:
            print(f"\n  {get_color(80)}⚠️  ADVERTENCIA: {pg['slow_queries']} queries lentas detectadas{reset_color()}")

    # Redis
    print("\n🔴 REDIS")
    print("-" * 70)
    redis_m = get_redis_metrics()

    if 'error' in redis_m:
        print(f"⚠️  Error: {redis_m['error']}")
    else:
        mem_percent = (redis_m['used_memory_mb'] / redis_m['max_memory_mb'] * 100) if redis_m['max_memory_mb'] > 0 else 0
        print(f"Memoria:     {format_bar(mem_percent, 20)} "
              f"({redis_m['used_memory_mb']:.1f}MB / {redis_m['max_memory_mb']:.0f}MB)")
        print(f"Clientes:    {redis_m['connected_clients']}")
        print(f"Keys:        {redis_m['keys_total']:,}")
        print(f"Ops/seg:     {redis_m['ops_per_sec']}")
        print(f"Hit Rate:    {redis_m['hit_rate']:.1f}%")

    # Gunicorn
    print("\n🦄 GUNICORN")
    print("-" * 70)
    workers = get_gunicorn_workers()
    threads = 2  # De Dockerfile

    if workers > 0:
        # Usar conexiones activas de PG como proxy de requests activas
        pg_active = pg.get('active_connections', 0) if 'error' not in pg else 0
        capacity = calculate_capacity(pg_active, workers, threads)

        print(f"Workers:     {workers}")
        print(f"Threads/Worker: {threads}")
        print(f"Capacidad Máxima: {capacity['max_concurrent']} requests concurrentes")
        print(f"Uso Actual:  {format_bar(capacity['usage_percent'], 20)} "
              f"({capacity['active_requests']}/{capacity['max_concurrent']})")
        print(f"\n💡 Usuarios Estimados: {get_color(capacity['usage_percent'])}{capacity['estimated_users']}{reset_color()} "
              f"usuarios activos (basado en 300ms/req, 3 req/min)")
    else:
        print("⚠️  No se detectaron workers de Gunicorn")
        print("   (puede ser normal si estás usando Flask dev server)")

    # Recomendaciones
    print("\n" + "=" * 70)
    print("📋 RECOMENDACIONES")
    print("-" * 70)

    recommendations = []

    if system['cpu_percent'] > 80:
        recommendations.append("🔴 CPU alta (>80%) - Considera escalar verticalmente u horizontalmente")

    if system['memory_percent'] > 80:
        recommendations.append("🔴 RAM alta (>80%) - Revisa memory leaks o aumenta RAM")

    if 'error' not in pg:
        conn_percent = (pg['total_connections'] / pg['max_total'] * 100) if pg['max_total'] > 0 else 0
        if conn_percent > 70:
            recommendations.append(f"🟡 Conexiones DB al {conn_percent:.0f}% - Considera aumentar pool_size")

        if pg['slow_queries'] > 3:
            recommendations.append(f"🔴 {pg['slow_queries']} queries lentas - Optimiza queries o agrega índices")

    if 'error' not in redis_m:
        if mem_percent > 80:
            recommendations.append("🟡 Redis memoria alta - Considera aumentar maxmemory")

    if workers > 0:
        if capacity['usage_percent'] > 70:
            recommendations.append(f"🔴 Gunicorn al {capacity['usage_percent']:.0f}% - URGENTE: Aumenta workers")
        elif capacity['usage_percent'] > 50:
            recommendations.append(f"🟡 Gunicorn al {capacity['usage_percent']:.0f}% - Planea aumentar workers pronto")

    if recommendations:
        for rec in recommendations:
            print(f"  • {rec}")
    else:
        print(f"  {get_color(30)}✅ Sistema operando dentro de parámetros normales{reset_color()}")

    print("\n" + "=" * 70)
    print("💡 Presiona Ctrl+C para salir | Actualización cada 5 segundos")
    print("=" * 70)


def main():
    """Ejecutar monitor en loop."""
    print("Iniciando monitor de concurrencia...")
    print("Esperando 2 segundos...")
    time.sleep(2)

    try:
        while True:
            try:
                display_metrics()
                time.sleep(5)  # Actualizar cada 5 segundos
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"\n❌ Error obteniendo métricas: {e}")
                print("Reintentando en 5 segundos...")
                time.sleep(5)
    except KeyboardInterrupt:
        print("\n\n✅ Monitor detenido por el usuario")
        sys.exit(0)


if __name__ == '__main__':
    main()
