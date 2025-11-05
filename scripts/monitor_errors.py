#!/usr/bin/env python3
"""
Script de Monitoreo de Logs de Error
=====================================
Monitorea los archivos de log en tiempo real y muestra errores y warnings.

Uso:
    python scripts/monitor_errors.py              # Últimos 50 errores
    python scripts/monitor_errors.py --tail       # Seguir en tiempo real
    python scripts/monitor_errors.py --count      # Solo contar por tipo
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import time

# Agregar el directorio raíz al path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

LOGS_DIR = ROOT_DIR / "logs"


def get_log_files():
    """Obtiene rutas de archivos de log"""
    return {
        'app': LOGS_DIR / 'app.log',
        'errors': LOGS_DIR / 'errors.log',
        'security': LOGS_DIR / 'security.log',
        'performance': LOGS_DIR / 'performance.log',
    }


def parse_log_line(line):
    """Parsea una línea de log"""
    try:
        # Formato: [2025-11-02 19:55:30,287] WARNING in app: Message
        if not line.strip():
            return None

        parts = line.split(']', 1)
        if len(parts) < 2:
            return None

        timestamp_part = parts[0].replace('[', '').strip()
        rest = parts[1].strip()

        # Extraer nivel
        level_parts = rest.split(' in ', 1)
        if len(level_parts) < 2:
            return None

        level = level_parts[0].strip()
        rest = level_parts[1]

        # Extraer módulo y mensaje
        msg_parts = rest.split(': ', 1)
        module = msg_parts[0].strip()
        message = msg_parts[1].strip() if len(msg_parts) > 1 else ''

        return {
            'timestamp': timestamp_part,
            'level': level,
            'module': module,
            'message': message,
            'raw': line
        }
    except:
        return None


def read_recent_logs(log_file, max_lines=50):
    """Lee las últimas líneas de un archivo de log"""
    if not log_file.exists():
        return []

    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return lines[-max_lines:]
    except:
        return []


def count_by_level(log_file):
    """Cuenta errores por nivel"""
    lines = read_recent_logs(log_file, max_lines=1000)
    counts = defaultdict(int)

    for line in lines:
        parsed = parse_log_line(line)
        if parsed:
            counts[parsed['level']] += 1

    return counts


def print_error_summary(log_files):
    """Imprime resumen de errores"""
    print("\n" + "="*70)
    print("  OBYRA - Resumen de Logs")
    print("="*70)

    for name, log_file in log_files.items():
        if not log_file.exists():
            print(f"\n❌ {name.upper()}: Archivo no encontrado")
            continue

        counts = count_by_level(log_file)
        if not counts:
            print(f"\n✅ {name.upper()}: Sin errores recientes")
            continue

        print(f"\n📋 {name.upper()} - {log_file.name}")
        for level in ['ERROR', 'CRITICAL', 'WARNING', 'INFO']:
            if level in counts:
                icon = {'ERROR': '🔴', 'CRITICAL': '💥', 'WARNING': '🟡', 'INFO': '🔵'}
                print(f"  {icon.get(level, '•')} {level:10} {counts[level]:,}")

    print("\n" + "="*70)


def print_recent_errors(log_files, max_lines=20):
    """Imprime errores recientes"""
    print("\n" + "="*70)
    print("  ÚLTIMOS ERRORES Y WARNINGS")
    print("="*70 + "\n")

    all_errors = []

    for name, log_file in log_files.items():
        if name == 'performance':  # Skip performance log
            continue

        lines = read_recent_logs(log_file, max_lines=100)
        for line in lines:
            parsed = parse_log_line(line)
            if parsed and parsed['level'] in ['ERROR', 'CRITICAL', 'WARNING']:
                parsed['log_type'] = name
                all_errors.append(parsed)

    # Ordenar por timestamp (últimos primero)
    all_errors = sorted(all_errors, key=lambda x: x['timestamp'], reverse=True)[:max_lines]

    if not all_errors:
        print("✅ No se encontraron errores o warnings recientes\n")
        return

    for error in all_errors:
        icon = {'ERROR': '🔴', 'CRITICAL': '💥', 'WARNING': '🟡'}.get(error['level'], '•')
        print(f"{icon} [{error['timestamp']}] {error['level']} ({error['log_type']})")
        print(f"   {error['module']}: {error['message'][:100]}")
        print()


def tail_logs(log_files):
    """Sigue los logs en tiempo real"""
    print("\n" + "="*70)
    print("  MONITOREANDO LOGS EN TIEMPO REAL")
    print("  Presiona Ctrl+C para detener")
    print("="*70 + "\n")

    # Abrir todos los archivos
    files = {}
    for name, log_file in log_files.items():
        if log_file.exists():
            files[name] = open(log_file, 'r')
            files[name].seek(0, 2)  # Ir al final

    try:
        while True:
            for name, f in files.items():
                line = f.readline()
                if line:
                    parsed = parse_log_line(line)
                    if parsed and parsed['level'] in ['ERROR', 'CRITICAL', 'WARNING']:
                        icon = {'ERROR': '🔴', 'CRITICAL': '💥', 'WARNING': '🟡'}.get(parsed['level'], '•')
                        print(f"{icon} [{parsed['timestamp']}] {parsed['level']} ({name})")
                        print(f"   {parsed['module']}: {parsed['message']}")
                        print()

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\nMonitoreo detenido por el usuario")
    finally:
        for f in files.values():
            f.close()


def main():
    """Función principal"""
    args = sys.argv[1:]

    # Verificar que el directorio de logs existe
    if not LOGS_DIR.exists():
        print(f"ERROR: Directorio de logs no encontrado: {LOGS_DIR}")
        sys.exit(1)

    log_files = get_log_files()

    if '--tail' in args or '-f' in args:
        tail_logs(log_files)
    elif '--count' in args or '-c' in args:
        print_error_summary(log_files)
    else:
        print_error_summary(log_files)
        print_recent_errors(log_files, max_lines=20)

        print("\n💡 TIPS:")
        print("  • Ver en tiempo real: python scripts/monitor_errors.py --tail")
        print("  • Solo conteo:        python scripts/monitor_errors.py --count")
        print(f"  • Logs guardados en:  {LOGS_DIR}\n")


if __name__ == '__main__':
    main()
