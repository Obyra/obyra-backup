# Backups y Recuperación ante Desastres

## Objetivos
- Garantizar recuperación puntual (PITR) hasta 15 minutos atrás en producción.
- Verificar mensualmente la restauración y documentación del proceso.
- Mantener retenciones diferenciadas por ambiente para optimizar costos.

## Estrategia de backups
### Local
- Utilizar `pg_dump` manual antes de pruebas destructivas (`make db.reset.local` realiza drop/recreate controlado).
- No se almacenan backups prolongados; cada desarrollador gestiona su entorno.

### Staging
- Backups automáticos diarios + WAL para PITR 7 días.
- Retención de snapshots semanales por 4 semanas.
- Almacenamiento cifrado en repositorio del proveedor (Neon / S3 privado).

### Producción
- PITR mediante WAL continuo con retención de 14 días.
- Snapshots diarios retenidos 35 días.
- Snapshot mensual archivado 12 meses para auditoría.
- Réplica en región secundaria con lag máximo 5 minutos.

## Pruebas de restore
- Staging: restaurar snapshot mensual en base aislada y ejecutar `alembic upgrade head` + smoke tests de aplicación.
- Producción: simulacro trimestral en entorno dedicado (clonado) verificando:
  1. Recuperación a punto en el tiempo T-15 minutos.
  2. Integridad del esquema `app` y conteo de registros críticos.
  3. Destrucción segura del entorno temporal.
- Documentar hallazgos en el runbook y ajustar procedimientos.

## Runbook de recuperación
1. Declarar incidente, congelar despliegues y notificar stakeholders.
2. Determinar alcance y punto objetivo de recuperación (timestamp exacto o snapshot).
3. Provisionar instancia temporal desde snapshot/WAL.
4. Validar integridad ejecutando `SELECT 1 FROM app.alembic_version` y pruebas críticas.
5. Promover la instancia recuperada a producción o migrar datos necesarios.
6. Actualizar credenciales (`DATABASE_URL`, `READONLY_DATABASE_URL`) y reiniciar servicios.
7. Documentar el incidente (post-mortem) y revisar métricas de RTO/RPO.

## Retención y cumplimiento
- Revisar retenciones trimestralmente para cumplir requisitos legales locales.
- Asegurar cifrado en reposo (KMS del proveedor) y en tránsito.
- Mantener lista de control de accesos a backups en `docs/db/checklists/security.md`.
