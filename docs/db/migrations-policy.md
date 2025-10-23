# Política de Migraciones (Alembic)

Esta política aplica a todas las migraciones gestionadas con Alembic en el esquema `app`.

## Convenciones
- Los archivos siguen el formato `<revision>_<descripcion>.py` en minúsculas y separados por guiones bajos.
- Cada migración incluye docstring inicial con propósito, precondiciones y pasos de verificación.
- Usar funciones helper del seed estructural para permisos/roles.

## Autogenerate
- Ejecutar `alembic revision --autogenerate -m "mensaje"` solo después de revisar los modelos y el estado de la DB local.
- Revisar manualmente el diff generado: eliminar alteraciones ajenas al esquema `app` y garantizar que se usan operaciones idempotentes cuando sea posible.
- Guardar los diffs para revisión por pares antes de hacer commit.

## Compatibilidad hacia adelante
- Las migraciones deben ser seguras en modo rolling deploy. Evitar acciones destructivas en el mismo script.
- Cambios que rompen compatibilidad (renombres de columnas, drops) requieren enfoque de dos pasos:
  1. Agregar columna/campo nuevo manteniendo los existentes.
  2. Migrar datos y actualizar aplicación.
  3. Remover columnas antiguas en ventana posterior.
- Evitar `ALTER TYPE ... RENAME VALUE` o `DROP COLUMN` sin estrategia de despliegue gradual.

## Ventanas de despliegue
- Staging: libre, pero siempre ejecutar en horario laboral para soporte rápido.
- Producción: dentro de ventanas semanales definidas por operaciones (ej. martes y jueves 09:00-11:00 ART).
- Cambios de alto riesgo requieren aprobación del responsable técnico y runbook asociado.

## Proceso estándar
1. Actualizar branch y ejecutar `alembic upgrade head` localmente.
2. Crear nueva migración con `alembic revision` (autogenerate o manual) apuntando a `app`.
3. Revisar el archivo, agregar `op.execute` con comentarios si se manipulan datos.
4. Ejecutar `alembic upgrade head` y `alembic downgrade -1` para validar.
5. Crear PR con checklist de revisión y adjuntar salida de CI (`db-ci`).

## Rollback
- Rollback inmediato: `alembic downgrade -1` sobre la última migración (debe ser reversible).
- Rollback parcial: escribir script específico documentado en el runbook.
- Runbook general:
  1. Identificar la migración problemática en `alembic history --verbose`.
  2. Coordinar ventana de mantenimiento con soporte.
  3. Ejecutar `alembic downgrade <revision>` usando `ALEMBIC_DATABASE_URL`.
  4. Validar estado con `alembic upgrade head` en entorno aislado antes de reabrir tráfico.
  5. Documentar en post-mortem y actualizar migración si es necesario.

## Dos pasos y limpieza
- Para columnas/drop: implementar migraciones separadas: `*_add_new_column` seguida por `*_cleanup_old_column`.
- Usar seeds idempotentes para datos estructurales (roles, catálogos).
- Mantener scripts de limpieza en carpeta `alembic/versions/legacy_cleanup/` si son posteriores a cambios en producción.

## Ventanas largas / locking
- Para operaciones costosas (`ALTER TABLE ... SET NOT NULL`, `CREATE INDEX CONCURRENTLY`) planificar en ventanas dedicadas.
- Preferir índices concurrentes y migraciones por lotes.
- Documentar estimaciones de tiempo y métricas (tiempo de ejecución previo) en el docstring de la migración.
