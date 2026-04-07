# Plan: Descomponer calculadora_ia.py

## Estado actual

`calculadora_ia.py` tiene **3947 líneas** y es el archivo más grande del proyecto.
Pero a diferencia de `obras.py` o `blueprint_presupuestos.py`, **NO es un Flask blueprint** — es un módulo de funciones puras y constantes de datos.

## Composición

- ~70% son **diccionarios de datos** (constantes hardcodeadas):
  - `COEFICIENTES_CONSTRUCCION` (línea 43)
  - `ETAPAS_CONSTRUCCION` (línea 201, ~220 líneas)
  - `TIPO_MULTIPLICADOR` (línea 424)
  - `PRECIO_REFERENCIA` (línea 432, ~800 líneas)
  - `FACTORES_SUPERFICIE_ETAPA` (línea 1220, ~270 líneas)
  - `ETAPA_REGLAS_BASE` (línea 1494, ~1200 líneas — el más grande)

- ~30% son **funciones de cálculo** (~25 funciones)

## Por qué NO se descompuso en Fase 3

1. **Sin riesgo de mantenibilidad inmediato**: Las constantes son tablas de datos, no lógica que cambie frecuentemente. Solo se editan ocasionalmente.

2. **Sin imports circulares**: A diferencia de `obras.py` que tenía decenas de rutas e imports cruzados, este módulo es autocontenido.

3. **Riesgo de descomposición alto**: Las funciones tienen dependencias internas con las constantes en orden específico. Mover cosas puede cambiar sutilmente el comportamiento.

4. **Beneficio cuestionable**: Un módulo Python de 3947 líneas con tablas de datos no es problemático. Los IDEs lo manejan bien.

## Alternativa más simple (recomendada)

En lugar de descomponer todo el archivo, **extraer SOLO las constantes más grandes a archivos JSON o YAML**:

```python
# calculadora_ia.py se reduciría a ~700 líneas
import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent / 'data' / 'calculadora'

with open(_DATA_DIR / 'precio_referencia.json') as f:
    PRECIO_REFERENCIA = json.load(f)

with open(_DATA_DIR / 'etapa_reglas_base.json') as f:
    ETAPA_REGLAS_BASE = json.load(f)

# ... resto del módulo igual
```

**Beneficios:**
- Constantes editables sin tocar Python
- Reduce el archivo de 3947 → ~700 líneas
- No-devs pueden actualizar precios
- Versionable en JSON

**Riesgos:**
- Necesita validar que el JSON tenga el mismo formato que los dicts Python
- Decimal vs float: hay que ser cuidadoso

## Plan de ejecución (cuando se haga)

1. Crear `data/calculadora/` directory
2. Por cada constante grande:
   - Convertir el dict Python a JSON (cuidado con `Decimal()`)
   - Guardar como `nombre_constante.json`
   - Reemplazar el dict por `json.load()`
3. Agregar tests que verifiquen que los valores cargados son idénticos a los originales
4. Validar que `calcular_etapas_seleccionadas()` devuelve los mismos resultados antes/después

## Estimación

- 1-2 días con tests
- Riesgo bajo si se hace con backup del archivo original

## Por ahora

`calculadora_ia.py` queda **tal cual está**. Funciona bien, no rompe nada, y descomponerlo prematuramente sería un cambio de bajo valor con riesgo no nulo.

Lo que SÍ se hizo en Fase 3:
- Descomponer `obras.py` (CRÍTICO, era un blueprint con 93 rutas)
- Descomponer `blueprint_presupuestos.py` (CRÍTICO, 33 rutas + lógica de pagos)
- Eliminar `presupuestos.py` muerto
- Extraer migraciones de `app.py`
- Unificar imports `from app import db`
