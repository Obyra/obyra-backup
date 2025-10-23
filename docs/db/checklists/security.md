# Checklist de Seguridad de Base de Datos

## Accesos y roles
- [ ] Revisar vigencia de roles `obyra_app`, `obyra_migrator`, `obyra_readonly`.
- [ ] Validar que solo los grupos autorizados tengan acceso a las credenciales en el secret manager.
- [ ] Confirmar rotación de contraseñas (<= 90 días) y actualizar en CI/CD.
- [ ] Verificar que `obyra_migrator` no posea permisos de login permanentes en producción.

## Conexiones y TLS
- [ ] Comprobar que `DATABASE_URL`, `ALEMBIC_DATABASE_URL` y `READONLY_DATABASE_URL` usan TLS (`sslmode=require`).
- [ ] Validar certificados del pooler y fechas de expiración.
- [ ] Revisar configuración de pooler para limitar conexiones por IP.

## search_path y RLS
- [ ] Confirmar `search_path` fijado a `app,public` para roles de la aplicación.
- [ ] Revisar políticas de RLS si existieran y que estén activas para tablas sensibles.
- [ ] Asegurar que ninguna migración modifica `search_path` global sin justificación.

## Logging y auditoría
- [ ] Validar que `pg_stat_statements` está habilitado y recolectando datos.
- [ ] Revisar logs de consultas lentas (< 1s en staging, < 2s en producción).
- [ ] Confirmar envío de logs a la plataforma central (ELK/CloudWatch).

## Rotación y housekeeping
- [ ] Documentar próxima rotación de secretos en calendario compartido.
- [ ] Verificar limpieza de usuarios obsoletos o sin uso > 90 días.
- [ ] Asegurar que backups cifrados solo son accesibles por el equipo autorizado.
- [ ] Registrar resultados de esta checklist en el tablero de cumplimiento.
