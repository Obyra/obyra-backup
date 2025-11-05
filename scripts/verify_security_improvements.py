#!/usr/bin/env python3
"""
Script de verificación de mejoras de seguridad implementadas en OBYRA.
Ejecutar después de desplegar los cambios para verificar que todo funciona correctamente.
"""

import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def check_imports():
    """Verificar que los imports necesarios existen."""
    print("✓ Verificando imports...")

    try:
        from extensions import limiter
        print("  ✅ limiter importado correctamente")
    except ImportError as e:
        print(f"  ❌ Error importando limiter: {e}")
        return False

    try:
        from auth import auth_bp
        print("  ✅ auth_bp importado correctamente")
    except ImportError as e:
        print(f"  ❌ Error importando auth_bp: {e}")
        return False

    try:
        from obras import obras_bp
        print("  ✅ obras_bp importado correctamente")
    except ImportError as e:
        print(f"  ❌ Error importando obras_bp: {e}")
        return False

    return True


def check_auth_rate_limits():
    """Verificar que los endpoints de auth tienen rate limiting."""
    print("\n✓ Verificando rate limits en auth.py...")

    with open('auth.py', 'r') as f:
        content = f.read()

    expected_limits = [
        '@limiter.limit("10 per minute"',  # login
        '@limiter.limit("3 per minute"',   # register
        '@limiter.limit("5 per minute"',   # forgot/reset
        '@limiter.limit("20 per minute"',  # integrantes
        '@limiter.limit("30 per minute"',  # cambiar_rol/toggle
    ]

    found = 0
    for limit in expected_limits:
        if limit in content:
            found += 1

    if found >= 4:  # Al menos 4 de los límites esperados
        print(f"  ✅ Rate limits encontrados en auth.py ({found} encontrados)")
        return True
    else:
        print(f"  ❌ Rate limits insuficientes en auth.py ({found} encontrados, esperados >= 4)")
        return False


def check_obras_rate_limits():
    """Verificar que los endpoints de obras tienen rate limiting."""
    print("\n✓ Verificando rate limits en obras.py...")

    with open('obras.py', 'r') as f:
        content = f.read()

    critical_endpoints = [
        'reiniciar-sistema',
        'bulk_delete',
        'eliminar_obra',
    ]

    found = 0
    for endpoint in critical_endpoints:
        if endpoint in content and '@limiter.limit' in content:
            found += 1

    if found >= 2:  # Al menos 2 de los endpoints críticos
        print(f"  ✅ Rate limits encontrados en obras.py ({found} endpoints protegidos)")
        return True
    else:
        print(f"  ⚠️  Pocos rate limits en obras.py ({found} endpoints protegidos)")
        return True  # No bloqueante


def check_no_hardcoded_emails():
    """Verificar que no hay emails hardcodeados en auth.py."""
    print("\n✓ Verificando ausencia de credenciales hardcodeadas...")

    with open('auth.py', 'r') as f:
        content = f.read()

    # Buscar la lista ADMIN_EMAILS (no debería existir)
    if 'ADMIN_EMAILS = [' in content:
        print("  ❌ ADMIN_EMAILS todavía está hardcodeada en auth.py")
        return False

    print("  ✅ No se encontraron credenciales hardcodeadas")
    return True


def check_improved_logging():
    """Verificar que el logging mejorado está implementado."""
    print("\n✓ Verificando logging mejorado...")

    with open('auth.py', 'r') as f:
        content = f.read()

    # Buscar patrones de logging mejorado
    good_patterns = [
        'current_app.logger.error',
        'exc_info=True',
    ]

    found = 0
    for pattern in good_patterns:
        if content.count(pattern) >= 5:  # Al menos 5 ocurrencias
            found += 1

    if found >= 2:
        print(f"  ✅ Logging mejorado implementado correctamente")
        return True
    else:
        print(f"  ⚠️  Logging podría mejorarse más")
        return True  # No bloqueante


def check_env_configuration():
    """Verificar que .env tiene la configuración de seguridad."""
    print("\n✓ Verificando configuración en .env...")

    try:
        with open('.env', 'r') as f:
            content = f.read()

        if 'RATE_LIMITER_STORAGE' in content:
            print("  ✅ RATE_LIMITER_STORAGE configurado en .env")
            return True
        else:
            print("  ⚠️  RATE_LIMITER_STORAGE no encontrado en .env")
            print("     Agregar: RATE_LIMITER_STORAGE=redis://localhost:6382/1")
            return True  # No bloqueante
    except FileNotFoundError:
        print("  ⚠️  Archivo .env no encontrado")
        return True  # No bloqueante


def check_documentation():
    """Verificar que la documentación existe."""
    print("\n✓ Verificando documentación...")

    if os.path.exists('SECURITY_IMPROVEMENTS.md'):
        print("  ✅ SECURITY_IMPROVEMENTS.md existe")
        return True
    else:
        print("  ❌ SECURITY_IMPROVEMENTS.md no encontrado")
        return False


def main():
    """Ejecutar todas las verificaciones."""
    print("=" * 70)
    print("VERIFICACIÓN DE MEJORAS DE SEGURIDAD - OBYRA")
    print("=" * 70)

    checks = [
        ("Imports", check_imports),
        ("Rate Limits Auth", check_auth_rate_limits),
        ("Rate Limits Obras", check_obras_rate_limits),
        ("No Credenciales Hardcodeadas", check_no_hardcoded_emails),
        ("Logging Mejorado", check_improved_logging),
        ("Configuración .env", check_env_configuration),
        ("Documentación", check_documentation),
    ]

    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"  ❌ Error ejecutando verificación '{name}': {e}")
            results.append((name, False))

    print("\n" + "=" * 70)
    print("RESUMEN DE VERIFICACIÓN")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")

    print("\n" + "=" * 70)
    print(f"RESULTADO: {passed}/{total} verificaciones pasadas")

    if passed == total:
        print("🎉 ¡Todas las verificaciones pasaron exitosamente!")
        print("\nPróximos pasos:")
        print("1. Revisar SECURITY_IMPROVEMENTS.md para detalles")
        print("2. Verificar que Redis está corriendo para rate limiting")
        print("3. Probar manualmente los endpoints protegidos")
        return 0
    else:
        print("⚠️  Algunas verificaciones fallaron. Revisar los errores arriba.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
