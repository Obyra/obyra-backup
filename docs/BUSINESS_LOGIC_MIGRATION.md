# Plan: Migrar lógica de negocio de vistas a servicios

## Estado actual

OBYRA ya tiene una capa `services/` con buenos servicios:
- `BaseService` con CRUD genérico + excepciones tipadas
- `ProjectService`, `BudgetService`, `InventoryService`
- `MarketplaceService`, `UserService`
- `ProjectSharedService` para lógica compartida

**Pero** los blueprints todavía contienen lógica de negocio embebida en las funciones de vista. Ejemplo típico:

```python
# ANTES: lógica en la vista
@obras_bp.route('/obras/<int:id>/certificar', methods=['POST'])
def certificar(id):
    obra = Obra.query.filter_by(id=id, organizacion_id=get_current_org_id()).first_or_404()

    # 50 líneas de cálculos, validaciones, queries adicionales
    items = ...
    total = sum(...)
    if total > obra.presupuesto * 1.1:
        return jsonify({'error': '...'}), 400

    cert = WorkCertification(...)
    db.session.add(cert)
    db.session.commit()

    notificar_admins(...)
    return jsonify({'ok': True, 'cert_id': cert.id})
```

Versus el patrón ideal:

```python
# DESPUÉS: vista delgada
@obras_bp.route('/obras/<int:id>/certificar', methods=['POST'])
def certificar(id):
    try:
        cert = CertificationService.create(
            obra_id=id,
            user=current_user,
            data=request.json,
        )
        return api_success(data={'cert_id': cert.id})
    except ValidationException as e:
        return api_validation_error(str(e))
    except PermissionDeniedException:
        return api_forbidden()
```

## Por qué no se hizo en Fase 3

1. **Trabajo continuo**: Son ~93 rutas en obras + 33 en presupuestos + cientos más
2. **Riesgo de regresiones**: Cada migración puede introducir bugs sutiles
3. **Sin tests**: Imposible verificar que la lógica migrada funciona igual

## Estrategia recomendada

### No migrar todo a la vez

Esta es una refactorización **incremental** que se hace gradualmente:

1. **Cada nuevo endpoint**: usar el patrón thin controller + service
2. **Cada bug fix**: oportunidad para extraer lógica al servicio
3. **Cada feature**: revisar si la lógica vieja se puede limpiar

### Priorizar servicios faltantes

Servicios que **deberían existir** pero hoy no:
- `CertificationService` (lógica está en obras/certificaciones.py)
- `LiquidacionMOService` (idem)
- `RemitoService` (en obras/remitos.py)
- `EquipmentMovementService` (en obras/equipos.py)
- `WizardService` (en obras/wizard.py)

### Convención

```python
# services/foo_service.py
from services.base import BaseService, ValidationException, NotFoundException

class FooService(BaseService):
    model = Foo  # Modelo SQLAlchemy

    @classmethod
    def create(cls, **data):
        cls._validate(data)
        instance = cls.model(**data)
        db.session.add(instance)
        db.session.commit()
        return instance

    @classmethod
    def _validate(cls, data):
        if not data.get('nombre'):
            raise ValidationException('Nombre requerido')
        # ... más validaciones
```

```python
# blueprint
from services.foo_service import FooService
from services.api_response import api_success, api_error

@bp.route('/foo', methods=['POST'])
@login_required
def crear_foo():
    try:
        foo = FooService.create(**request.form.to_dict())
        return api_success(data=foo.to_dict())
    except ValidationException as e:
        return api_error(str(e), status=400)
```

## Próximos pasos sugeridos

1. **Leer** `services/base.py` para entender el patrón
2. **Migrar 1 endpoint piloto** y medir si hay regresiones
3. **Documentar** el patrón con ejemplos reales del repo
4. **Establecer** la regla: nuevo código = thin controller obligatorio

## Estimación

- **Una ruta promedio**: 30-60 minutos
- **Toda la migración**: 2-3 meses con 1 dev part-time
- **Mejor estrategia**: hacerlo orgánico, no como big bang
