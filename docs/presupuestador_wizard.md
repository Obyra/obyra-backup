# Presupuestador Wizard v2

Este módulo extiende el wizard de tareas para estimar automáticamente el presupuesto por etapa con desglose de materiales, mano de obra y equipos. El comportamiento nuevo está protegido por banderas de características y mantiene la lógica existente cuando la bandera está desactivada.

## Activar el cálculo integral

1. Actualiza la base de datos ejecutando el comando de migraciones livianas (se puede correr tantas veces como sea necesario):

   ```bash
   flask db upgrade
   ```

   Esto crea las tablas `wizard_stage_variants` y `wizard_stage_coefficients` y carga coeficientes baseline iniciales.

2. Define las variables de entorno antes de iniciar la aplicación:

   ```bash
   export WIZARD_BUDGET_BREAKDOWN_ENABLED=1
   export WIZARD_BUDGET_SHADOW_MODE=1  # opcional, activa el modo sombra para comparar con el flujo actual
   ```

   Si `WIZARD_BUDGET_SHADOW_MODE` no se define, permanece desactivado para evitar ruido de logs.

3. Reinicia la aplicación. El paso 3 del wizard mostrará la columna de variantes y el paso 4 incluirá el cuadro de presupuesto con el desglose por etapa.

## Gestionar variantes y coeficientes técnicos

* Las variantes y coeficientes se almacenan en las tablas nuevas:
  * `wizard_stage_variants`: define las variantes disponibles por etapa (`stage_slug`, `variant_key`, `nombre`, `descripcion`).
  * `wizard_stage_coefficients`: guarda los coeficientes por unidad para materiales, mano de obra y equipos. Cada fila puede referenciar una variante (`variant_id`) o funcionar como baseline (`is_baseline = 1`).
* Los valores baseline iniciales (por ejemplo, excavación estándar, mampostería con ladrillo común, etc.) se cargan automáticamente al ejecutar `flask db upgrade` si la tabla está vacía.
* Para editar o agregar nuevas variantes/coefs se pueden usar herramientas como `flask shell`, pgAdmin/SQLite Browser o migraciones personalizadas. Ejemplo en `flask shell`:

  ```python
  from services.wizard_budgeting import seed_default_coefficients_if_needed
  from models import WizardStageVariant, WizardStageCoefficient
  from app.extensions import db

  variante = WizardStageVariant(stage_slug='mamposteria', variant_key='ladrillo_hueco', nombre='Ladrillo hueco')
  coef = WizardStageCoefficient(stage_slug='mamposteria', variant=variante, unit='m2', materials_per_unit=21000, labor_per_unit=14500, equipment_per_unit=3500, currency='ARS')
  db.session.add_all([variante, coef])
  db.session.commit()
  ```

* Los cambios se reflejan automáticamente en el endpoint `/api/wizard-tareas/opciones` y en el cálculo del presupuesto.

## Shadow mode y logs

* Con `WIZARD_BUDGET_BREAKDOWN_ENABLED=0` y `WIZARD_BUDGET_SHADOW_MODE=1`, el backend calcula el presupuesto en segundo plano y registra el resultado en los logs (`🕶️ WIZARD BUDGET ...`). Esto permite comparar con el flujo actual sin mostrarlo al usuario.
* Cuando el flag principal está en `1`, el cálculo se devuelve al frontend y se muestra en el paso 4 del wizard. El modo sombra puede mantenerse activo para dejar rastro adicional si se desea.

## Rollback rápido

* Para volver al comportamiento anterior basta con desactivar el flag principal:

  ```bash
  export WIZARD_BUDGET_BREAKDOWN_ENABLED=0
  ```

* No es necesario revertir cambios de base de datos: las tablas nuevas son aditivas y quedan inactivas si no se usa el flag.

## Checklist de regresión (wizard tareas)

Se recomienda repasar estos puntos cuando se active el cálculo integral:

- [ ] Paso 1: seleccionar múltiples etapas del catálogo y avanzar sin errores.
- [ ] Paso 2: marcar tareas en distintas etapas y verificar que el resumen lateral se actualiza.
- [ ] Paso 3: completar datos masivos, elegir variantes por etapa y confirmar que la columna aparece sólo con la bandera activa.
- [ ] Paso 4: validar que el cuadro de presupuesto muestra los totales por etapa, indica "Estimado" cuando corresponde y mantiene la lista de tareas.
- [ ] Crear las tareas y confirmar que la respuesta incluye `presupuesto` (con la bandera ON) o `presupuesto_shadow` (con la bandera OFF).
- [ ] Revisar logs para verificar los mensajes de shadow mode y que no existan errores.

> Nota: en entornos donde la UI no está disponible se puede ejercer el checklist mediante llamadas a los endpoints REST (`/api/wizard-tareas/*`).
