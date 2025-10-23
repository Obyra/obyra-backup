# Checklist de Release de Migraciones

## Preparación previa a `alembic upgrade`
- [ ] Revisar PR aprobado y confirmar que la migración cumple con la política de compatibilidad.
- [ ] Verificar que CI (`db-ci`) pasó en la rama a desplegar.
- [ ] Confirmar ventana de mantenimiento y notificar al equipo de soporte.
- [ ] Exportar `ALEMBIC_DATABASE_URL` con credenciales del rol `obyra_migrator`.

## Ejecución
- [ ] Ejecutar `alembic upgrade head` en staging y registrar timestamp.
- [ ] Revisar logs de la migración (stdout y logs de DB) buscando locks prolongados.
- [ ] Correr smoke tests de aplicación (ping de API, login básico, flujo crítico).
- [ ] Validar que `app.alembic_version` quedó en la revisión esperada.

## Post-despliegue
- [ ] Ejecutar consulta de verificación de datos/seed según la migración.
- [ ] Ejecutar `alembic history --verbose | tail -n 5` para documentación.
- [ ] Confirmar que el esquema `app` contiene las tablas esperadas (`\dn+ app`).
- [ ] Actualizar checklist de seguridad si se crearon nuevos roles/permisos.

## Rollback rápido
- [ ] Tener el comando `alembic downgrade -1` preparado con la misma credencial.
- [ ] Validar que no hay cambios de datos no reversibles antes de liberar el tráfico.
- [ ] Documentar resultado del release (éxito o rollback) en el canal de operaciones.
