# Plan de migración y mejoras para la aplicación

## Objetivos generales
- Migrar la infraestructura de datos desde SQLite hacia PostgreSQL (o un motor relacional administrado equivalente) garantizando disponibilidad y escalabilidad.
- Reestructurar la aplicación Flask para reducir el acoplamiento, eliminar duplicados y mejorar la mantenibilidad.
- Incorporar prácticas de despliegue, observabilidad y pruebas automatizadas acordes a entornos productivos multiusuario.
- Documentar el estado final de la plataforma para facilitar operaciones, soporte y futuras iteraciones.

## Fases y entregables

### Fase 1 · Descubrimiento y preparación (1-2 semanas)
1. **Inventario de dependencias y configuración**
   - Auditar variables de entorno actuales (`DATABASE_URL`, `SECRET_KEY`, proveedores externos) y documentar valores requeridos para staging/producción.
   - Revisar `pyproject.toml` y `requirements.txt` (si existiera) para identificar librerías huérfanas o versiones inseguras.
   - Entregable: documento de entorno con configuración mínima viable.

2. **Mapeo funcional del código**
   - Catalogar blueprints, servicios y modelos activos vs legacy (`app_old.py`, `marketplace_new.py`, etc.).
   - Elaborar diagrama de rutas y dependencias destacando módulos a deprecar.
   - Entregable: informe de arquitectura actual + backlog de módulos candidatos a eliminación/refactor.

3. **Definición de estrategia de base de datos**
   - Diseñar topología objetivo en PostgreSQL (instancia, esquema, roles, backups automáticos).
   - Establecer política de migraciones (por ejemplo, Alembic) y versionado de datos semilla.
   - Entregable: plan de infraestructura aprobado + checklist de acceso/seguridad.

### Fase 2 · Migración de base de datos (2-3 semanas)
4. **Provisionamiento de PostgreSQL**
   - Crear instancia gestionada (sup. AWS RDS, GCP Cloud SQL o similar) en ambiente de staging.
   - Configurar redes, parámetros de conexión y rotación de credenciales.
   - Entregable: base operativa con métricas y backups habilitados.

5. **Implementación de migraciones**
   - Integrar Alembic u otra herramienta de migración en el proyecto.
   - Generar esquemas a partir de modelos actuales, ajustando tipos incompatibles (por ejemplo, `JSON` vs `JSONB`).
   - Validar migraciones en SQLite → PostgreSQL con dataset de prueba.
   - Entregable: carpeta `migrations/` versionada + pipeline de migración reproducible.

6. **Carga y verificación de datos**
   - Exportar data existente desde SQLite (`.dump`) y transformarla cuando sea necesario (encoding, tipos booleanos, fechas).
   - Ejecutar migraciones y semillas en staging, comparar conteos y relaciones.
   - Entregable: reporte de QA de datos con validaciones automatizadas.

7. **Actualización de configuración de aplicación**
   - Ajustar `app.py`/`extensions.py` para leer credenciales de entorno y eliminar fallback silencioso a SQLite.
   - Revisar parámetros de pool (`pool_size`, `max_overflow`, timeouts) acorde a la nueva infraestructura.
   - Entregable: PR con configuración parametrizable y documentación actualizada.

### Fase 3 · Refactor de arquitectura y código (3-4 semanas)
8. **Modularización de la aplicación Flask**
   - Extraer creación de app y extensiones a `create_app()` en `__init__.py` estilo factory.
   - Aislar modelos, esquemas, servicios y blueprints en paquetes dedicados evitando importaciones circulares.
   - Entregable: estructura modularizada con tests de humo por blueprint.

9. **Depuración de código legacy**
   - Remover archivos duplicados (`app_old.py`, `marketplace_new.py`) tras confirmar que sus funcionalidades están cubiertas.
   - Documentar decisiones de eliminación en changelog interno.
   - Entregable: árbol de código limpio + reducción de deuda técnica.

10. **Cobertura de pruebas**
    - Crear suite mínima de `pytest` con fixtures para base de datos temporal.
    - Incluir pruebas para endpoints críticos (auth, marketplace, órdenes) y servicios clave.
    - Entregable: cobertura >40% inicial + integración en CI.

11. **Observabilidad y logging**
    - Centralizar configuración de logs (JSON estructurado, niveles por entorno).
    - Integrar herramientas de monitoreo/apm (Sentry, Prometheus/Grafana o equivalente).
    - Entregable: guías de diagnóstico y alertas básicas configuradas.

### Fase 4 · Despliegue y operación (1-2 semanas)
12. **Pipeline de CI/CD**
    - Configurar pipeline (GitHub Actions, GitLab CI, etc.) con pasos: lint, tests, build imagen, deploy.
    - Incorporar escaneo de seguridad (dependabot, pip-audit) y chequeos de calidad.
    - Entregable: pipeline reproducible con despliegues automatizados a staging.

13. **Contenerización y servidor WSGI**
    - Construir imagen Docker con `gunicorn`/`uwsgi`, configuración de workers y healthchecks.
    - Definir variables de entorno en runtime (SECRET_KEY, DATABASE_URL, proveedores externos).
    - Entregable: manifiestos de despliegue (Docker Compose/Kubernetes) y guía de rollback.

14. **Pruebas de carga y monitoreo**
    - Ejecutar pruebas de estrés (Locust, k6) sobre escenarios críticos.
    - Ajustar parámetros (pool, workers, caché) según resultados.
    - Entregable: informe de performance + recomendaciones finales.

15. **Cutover a producción**
    - Planificar ventana de migración, pasos de congelamiento de datos y verificación post-deploy.
    - Implementar monitoreo de humo post-lanzamiento y plan de reversión.
    - Entregable: acta de puesta en producción y checklist de soporte.

### Fase 5 · Documentación y transferencia (1 semana)
16. **Manual operativo y runbooks**
    - Redactar procedimientos para incidentes comunes, rotación de claves y backups.
    - Entregable: wiki actualizada.

17. **Capacitación y handover**
    - Sesión con equipo interno para repasar arquitectura, despliegue y planes de contingencia.
    - Entregable: acta de handover + backlog de mejoras futuras.

## Riesgos y mitigaciones
- **Pérdida de datos durante migración**: respaldos automáticos + pruebas de restauración antes del cutover.
- **Interrupción del servicio**: plan de contingencia con rollback documentado y ventana de mantenimiento anunciada.
- **Falta de alineación de stakeholders**: checkpoints semanales con responsables de negocio/tecnología para validar entregables.
- **Recursos limitados**: priorizar módulos de alto valor y mantener backlog visible para iteraciones posteriores.

## Métricas de éxito
- Tiempo de respuesta p95 < 500 ms bajo carga esperada.
- Errores 5xx < 1% tras migración.
- Cobertura de pruebas ≥ 60% en los siguientes 6 meses.
- MTTR < 30 minutos gracias a runbooks y observabilidad implementada.

## Roles sugeridos
- **Líder técnico**: coordina arquitectura, migración y revisiones de código.
- **DevOps/Infra**: aprovisiona PostgreSQL, CI/CD y monitoreo.
- **Backend devs**: refactor, pruebas y saneamiento de código legacy.
- **QA/Testing**: diseña y ejecuta pruebas funcionales y de carga.
- **Product owner**: prioriza funcionalidades y comunica con stakeholders.

## Próximos pasos inmediatos
1. Validar plan con dirección y asignar responsables por fase.
2. Crear tablero Kanban con tareas y dependencias explícitas.
3. Preparar entorno de staging para comenzar pruebas de migración.
