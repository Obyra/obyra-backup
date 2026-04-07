# Plan: Application Factory Pattern

## ¿Qué es?

Convertir `app.py` de:
```python
app = Flask(__name__)  # módulo nivel
app.config[...] = ...
# ... 1200 líneas de configuración
```

A:
```python
def create_app(config_name='production'):
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))
    init_extensions(app)
    register_blueprints(app)
    return app

# Para gunicorn:
app = create_app()
```

## Beneficios

1. **Tests aislados**: Cada test crea su instancia con config distinta
2. **Múltiples configs**: dev/test/prod sin if-else
3. **Sin imports circulares**: Las extensiones se inicializan en función, no a nivel módulo
4. **Reload más rápido**: Para desarrollo

## Por qué NO se hizo en Fase 3

### 1. app.py tiene 1257 líneas con configuración entremezclada
- Carga de feature flags
- Setup de session/cookies con lógica condicional
- Setup de OpenAI/MercadoPago
- Setup de Google OAuth
- Filtros Jinja personalizados
- Middleware de seguridad
- Registro de ~30 blueprints
- Hook de migración runtime
- Login manager con loaders
- CLI commands

### 2. Riesgo MUY alto sin tests
Cambiar el orden de inicialización puede romper:
- ProxyFix (debe ir antes de cualquier request handler)
- ProxyFix vs CSRF order
- Inicialización de Sentry (debe ser ANTES de Flask())
- Login manager (depende de db estar inicializado)

### 3. Beneficio depende de tener tests
La razón #1 para hacer Application Factory es facilitar tests. OBYRA hoy tiene 46 tests para 19,000 líneas. Hasta ampliar cobertura, el beneficio es marginal.

## Plan de ejecución (cuando se haga)

### Fase A — Preparación (sin riesgo)
1. Crear `obyra/__init__.py` con `create_app()` esqueleto
2. Crear `obyra/config.py` con classes `DevConfig`, `ProdConfig`, `TestConfig`
3. Crear `obyra/extensions.py` (mover desde `extensions.py`)
4. Mantener `app.py` legacy funcionando en paralelo

### Fase B — Migración gradual
1. Mover bloques de config de `app.py` a `obyra/config.py`
2. Mover registro de blueprints a `obyra/blueprints.py`
3. Mover middleware a `obyra/middleware.py`
4. Mover CLI commands a `obyra/cli.py`
5. Mover filtros Jinja a `obyra/template_filters.py`

### Fase C — Switch
1. `app.py` se convierte en wrapper minimalista:
   ```python
   from obyra import create_app
   app = create_app(os.getenv('FLASK_ENV', 'production'))
   ```
2. Verificar gunicorn arranca correctamente
3. Verificar todos los blueprints siguen registrados
4. Verificar tests pasan (los que haya)

### Fase D — Cleanup
1. Eliminar imports circulares restantes
2. Documentar el nuevo patrón

## Estimación

- **Sin tests**: 1-2 semanas, riesgo alto
- **Con tests robustos**: 3-5 días, riesgo bajo

## Recomendación

**Hacer DESPUÉS de Fase 4 (escalabilidad)** o cuando se inicie un sprint de tests. La descomposición de archivos gigantes (`obras/`, `blueprint_presupuestos/`) ya resolvió la mayoría del problema de mantenibilidad sin requerir Application Factory.

## Estado mínimo aceptable hoy

Lo que ya tenemos:
- ✅ `extensions.py` separado
- ✅ `from app import db` eliminado (29 archivos)
- ✅ `runtime_migrations.py` extraído
- ✅ Blueprints en paquetes (`obras/`, `blueprint_presupuestos/`)

Lo que faltaría:
- ❌ `create_app()` function
- ❌ Config classes
- ❌ Tests usando factory
