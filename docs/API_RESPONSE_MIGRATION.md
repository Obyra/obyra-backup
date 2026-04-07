# Guía de migración a `api_response`

OBYRA tiene 4 formatos distintos de respuesta JSON heredados. Este documento explica cómo migrar a `services/api_response.py`.

## Formato estándar nuevo

```json
{
  "ok": true|false,
  "data": <objeto opcional>,
  "error": "<mensaje opcional>",
  "message": "<mensaje opcional>"
}
```

## Antes / Después

### Caso 1: Respuesta de éxito con datos

```python
# ANTES (cualquiera de estos):
return jsonify({'ok': True, 'data': obras}), 200
return jsonify({'exito': True, 'presupuesto': pres})
return jsonify({'success': True, 'items': items})

# DESPUÉS:
from services.api_response import api_success
return api_success(data=obras)
return api_success(data={'presupuesto': pres})
return api_success(data={'items': items})
```

### Caso 2: Error genérico

```python
# ANTES:
except Exception as e:
    return jsonify({'ok': False, 'error': str(e)}), 500

# DESPUÉS:
from services.api_response import api_error
except Exception as e:
    return api_error('Error interno del servidor', status=500, exception=e)
```

`api_error` automáticamente:
- Loguea el error completo con stack trace
- NO expone el mensaje interno al cliente
- Devuelve un mensaje genérico seguro

### Caso 3: Recurso no encontrado

```python
# ANTES:
return jsonify({'error': 'Obra no encontrada'}), 404

# DESPUÉS:
from services.api_response import api_not_found
return api_not_found('Obra')
```

### Caso 4: No autorizado

```python
# ANTES:
return jsonify({'error': 'No tenés permisos'}), 403

# DESPUÉS:
from services.api_response import api_forbidden
return api_forbidden()
```

### Caso 5: Validación de campos

```python
# ANTES:
return jsonify({'ok': False, 'error': 'Datos inválidos'}), 400

# DESPUÉS:
from services.api_response import api_validation_error
return api_validation_error(
    'Datos inválidos',
    fields={'email': 'Email inválido', 'edad': 'Debe ser mayor a 18'}
)
```

## Estrategia de adopción gradual

No es necesario migrar todo a la vez. Cada nuevo endpoint que escribas o modifiques, usá `api_response`. Los archivos legacy pueden seguir funcionando con sus formatos viejos.

**Prioridad de migración:**
1. Endpoints nuevos
2. Endpoints que se modifiquen por bug fix
3. Archivos `blueprint_*.py` (el core API)
4. Resto del código

## Compatibilidad con el frontend

El frontend actual espera distintos formatos según el endpoint. Al migrar, verificar que:
- `response.ok` reemplaza a `response.exito`/`response.success`
- `response.data` contiene los datos (antes podían estar en la raíz)
- `response.error` es el único campo de error
