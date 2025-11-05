"""
Project Service - Gestión de obras, etapas y tareas
====================================================
Servicio para gestión completa de proyectos (obras), incluyendo:
- Creación y actualización de proyectos
- Cálculo de progreso automático
- Gestión de tareas (crear, actualizar, asignar)
- Gestión de etapas
- Seguimiento de avances y aprobaciones
- Asignaciones de usuarios a proyectos
- Cálculos EVM (Earned Value Management)
"""

from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from services.base import BaseService, ValidationException, NotFoundException, PermissionDeniedException
from extensions import db
from models import (
    Obra, EtapaObra, TareaEtapa, TareaMiembro, TareaAvance, TareaAvanceFoto,
    TareaPlanSemanal, TareaAvanceSemanal, TareaAdjunto, TareaResponsables,
    AsignacionObra, ObraMiembro, Usuario, resumen_tarea
)


class ProjectService(BaseService[Obra]):
    """
    Servicio para gestión de proyectos/obras.

    Proporciona funcionalidad completa para:
    - Gestión de proyectos (CRUD, pausar, reanudar)
    - Cálculo de progreso automático
    - Gestión de tareas y etapas
    - Seguimiento de avances
    - Asignaciones de personal
    - Métricas EVM
    """

    model_class = Obra

    # ===== PROJECT MANAGEMENT =====

    def create_project(self, data: Dict[str, Any]) -> Obra:
        """
        Crea un nuevo proyecto/obra.

        Args:
            data: Diccionario con los datos del proyecto. Campos requeridos:
                - nombre: Nombre del proyecto
                - cliente: Nombre del cliente
                - organizacion_id: ID de la organización
                  Campos opcionales: descripcion, direccion, presupuesto_total, etc.

        Returns:
            Obra: Instancia del proyecto creado

        Raises:
            ValidationException: Si faltan campos requeridos o datos inválidos
        """
        # Validar campos requeridos
        required_fields = ['nombre', 'cliente', 'organizacion_id']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            raise ValidationException(
                f"Campos requeridos faltantes: {', '.join(missing_fields)}",
                details={'missing_fields': missing_fields}
            )

        # Validar presupuesto si se proporciona
        if 'presupuesto_total' in data and data['presupuesto_total']:
            try:
                data['presupuesto_total'] = Decimal(str(data['presupuesto_total']))
                if data['presupuesto_total'] < 0:
                    raise ValidationException("El presupuesto no puede ser negativo")
            except (ValueError, TypeError):
                raise ValidationException("Presupuesto inválido")

        # Validar fechas
        if 'fecha_inicio' in data and 'fecha_fin_estimada' in data:
            if data['fecha_inicio'] and data['fecha_fin_estimada']:
                if data['fecha_inicio'] > data['fecha_fin_estimada']:
                    raise ValidationException(
                        "La fecha de inicio no puede ser posterior a la fecha de fin estimada"
                    )

        # Establecer valores por defecto
        data.setdefault('estado', 'planificacion')
        data.setdefault('progreso', 0)
        data.setdefault('costo_real', Decimal('0'))

        try:
            obra = self.create(**data)
            self._log_info(f"Proyecto creado: {obra.nombre} (ID: {obra.id})")
            return obra
        except Exception as e:
            self._log_error(f"Error al crear proyecto: {str(e)}")
            raise

    def update_project(self, project_id: int, data: Dict[str, Any]) -> Obra:
        """
        Actualiza un proyecto existente.

        Args:
            project_id: ID del proyecto
            data: Diccionario con los campos a actualizar

        Returns:
            Obra: Instancia del proyecto actualizado

        Raises:
            NotFoundException: Si el proyecto no existe
            ValidationException: Si los datos son inválidos
        """
        obra = self.get_by_id_or_fail(project_id)

        # Validar presupuesto si se actualiza
        if 'presupuesto_total' in data and data['presupuesto_total'] is not None:
            try:
                data['presupuesto_total'] = Decimal(str(data['presupuesto_total']))
                if data['presupuesto_total'] < 0:
                    raise ValidationException("El presupuesto no puede ser negativo")
            except (ValueError, TypeError):
                raise ValidationException("Presupuesto inválido")

        # Validar fechas
        fecha_inicio = data.get('fecha_inicio', obra.fecha_inicio)
        fecha_fin = data.get('fecha_fin_estimada', obra.fecha_fin_estimada)
        if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
            raise ValidationException(
                "La fecha de inicio no puede ser posterior a la fecha de fin estimada"
            )

        # Validar estado
        if 'estado' in data:
            estados_validos = ['planificacion', 'en_curso', 'pausada', 'finalizada', 'cancelada']
            if data['estado'] not in estados_validos:
                raise ValidationException(
                    f"Estado inválido. Debe ser uno de: {', '.join(estados_validos)}"
                )

        try:
            updated_obra = self.update(project_id, **data)
            self._log_info(f"Proyecto actualizado: {updated_obra.nombre} (ID: {project_id})")
            return updated_obra
        except Exception as e:
            self._log_error(f"Error al actualizar proyecto {project_id}: {str(e)}")
            raise

    def calculate_progress(self, project_id: int, auto_update: bool = True) -> Dict[str, Any]:
        """
        Calcula el progreso automático de un proyecto basado en etapas, tareas y certificaciones.

        Extrae la lógica de Obra.calcular_progreso_automatico() con mejoras.

        Args:
            project_id: ID del proyecto
            auto_update: Si es True, actualiza el campo progreso en la base de datos

        Returns:
            dict: Diccionario con información del progreso:
                - progreso_total: Porcentaje total (0-100)
                - progreso_etapas: Porcentaje por etapas
                - progreso_certificaciones: Porcentaje por certificaciones
                - total_etapas: Número de etapas
                - etapas_finalizadas: Número de etapas finalizadas
                - detalles_etapas: Lista con progreso por etapa

        Raises:
            NotFoundException: Si el proyecto no existe
        """
        obra = self.get_by_id_or_fail(project_id)

        total_etapas = obra.etapas.count()
        if total_etapas == 0:
            resultado = {
                'progreso_total': 0,
                'progreso_etapas': 0,
                'progreso_certificaciones': 0,
                'total_etapas': 0,
                'etapas_finalizadas': 0,
                'detalles_etapas': []
            }
            if auto_update:
                obra.progreso = 0
                db.session.commit()
            return resultado

        # Calcular progreso por etapas
        progreso_etapas = Decimal('0')
        etapas_finalizadas = 0
        detalles_etapas = []

        for etapa in obra.etapas:
            total_tareas = etapa.tareas.count()
            porcentaje_etapa = Decimal('0')

            if total_tareas > 0:
                tareas_completadas = etapa.tareas.filter_by(estado='completada').count()
                porcentaje_etapa = (
                    Decimal(str(tareas_completadas)) / Decimal(str(total_tareas))
                ) * (Decimal('100') / Decimal(str(total_etapas)))
                progreso_etapas += porcentaje_etapa
            elif etapa.estado == 'finalizada':
                porcentaje_etapa = Decimal('100') / Decimal(str(total_etapas))
                progreso_etapas += porcentaje_etapa
                etapas_finalizadas += 1

            detalles_etapas.append({
                'etapa_id': etapa.id,
                'nombre': etapa.nombre,
                'total_tareas': total_tareas,
                'tareas_completadas': etapa.tareas.filter_by(estado='completada').count() if total_tareas > 0 else 0,
                'porcentaje': float(porcentaje_etapa),
                'estado': etapa.estado
            })

        # Calcular progreso por certificaciones
        progreso_certificaciones = Decimal('0')
        for cert in obra.certificaciones.filter_by(activa=True):
            if cert.porcentaje_avance:
                progreso_certificaciones += Decimal(str(cert.porcentaje_avance))

        # El progreso total no puede exceder 100%
        progreso_total = min(Decimal('100'), progreso_etapas + progreso_certificaciones)
        progreso_total_int = int(progreso_total.quantize(Decimal('1'), rounding=ROUND_HALF_UP))

        # Actualizar en base de datos si se solicita
        if auto_update:
            obra.progreso = progreso_total_int
            db.session.commit()
            self._log_info(f"Progreso actualizado para proyecto {project_id}: {progreso_total_int}%")

        return {
            'progreso_total': progreso_total_int,
            'progreso_etapas': float(progreso_etapas),
            'progreso_certificaciones': float(progreso_certificaciones),
            'total_etapas': total_etapas,
            'etapas_finalizadas': etapas_finalizadas,
            'detalles_etapas': detalles_etapas
        }

    def can_pause(self, project_id: int, user_id: int) -> bool:
        """
        Verifica si un usuario puede pausar un proyecto.

        Extrae la lógica de Obra.puede_ser_pausada_por().

        Args:
            project_id: ID del proyecto
            user_id: ID del usuario

        Returns:
            bool: True si el usuario puede pausar el proyecto

        Raises:
            NotFoundException: Si el proyecto o usuario no existe
        """
        obra = self.get_by_id_or_fail(project_id)
        usuario = Usuario.query.get(user_id)

        if not usuario:
            raise NotFoundException('Usuario', user_id)

        return (
            usuario.rol == 'administrador' or
            getattr(usuario, 'puede_pausar_obras', False) or
            usuario.organizacion_id == obra.organizacion_id
        )

    def pause_project(self, project_id: int, user_id: int) -> Obra:
        """
        Pausa un proyecto.

        Args:
            project_id: ID del proyecto
            user_id: ID del usuario que pausa el proyecto

        Returns:
            Obra: Proyecto pausado

        Raises:
            NotFoundException: Si el proyecto no existe
            PermissionDeniedException: Si el usuario no tiene permisos
            ValidationException: Si el proyecto no puede ser pausado
        """
        if not self.can_pause(project_id, user_id):
            raise PermissionDeniedException('pausar', 'Proyecto')

        obra = self.get_by_id_or_fail(project_id)

        if obra.estado == 'pausada':
            raise ValidationException("El proyecto ya está pausado")

        if obra.estado in ['finalizada', 'cancelada']:
            raise ValidationException(
                f"No se puede pausar un proyecto en estado '{obra.estado}'"
            )

        obra.estado = 'pausada'
        db.session.commit()

        self._log_info(f"Proyecto {project_id} pausado por usuario {user_id}")
        return obra

    def resume_project(self, project_id: int, user_id: int) -> Obra:
        """
        Reanuda un proyecto pausado.

        Args:
            project_id: ID del proyecto
            user_id: ID del usuario que reanuda el proyecto

        Returns:
            Obra: Proyecto reanudado

        Raises:
            NotFoundException: Si el proyecto no existe
            PermissionDeniedException: Si el usuario no tiene permisos
            ValidationException: Si el proyecto no está pausado
        """
        if not self.can_pause(project_id, user_id):
            raise PermissionDeniedException('reanudar', 'Proyecto')

        obra = self.get_by_id_or_fail(project_id)

        if obra.estado != 'pausada':
            raise ValidationException("El proyecto no está pausado")

        obra.estado = 'en_curso'
        db.session.commit()

        self._log_info(f"Proyecto {project_id} reanudado por usuario {user_id}")
        return obra

    # ===== STAGE MANAGEMENT =====

    def create_stage(self, project_id: int, data: Dict[str, Any]) -> EtapaObra:
        """
        Crea una nueva etapa en un proyecto.

        Args:
            project_id: ID del proyecto
            data: Diccionario con los datos de la etapa. Campos requeridos:
                - nombre: Nombre de la etapa
                - orden: Orden de la etapa en el proyecto

        Returns:
            EtapaObra: Instancia de la etapa creada

        Raises:
            NotFoundException: Si el proyecto no existe
            ValidationException: Si faltan campos requeridos
        """
        obra = self.get_by_id_or_fail(project_id)

        # Validar campos requeridos
        if not data.get('nombre'):
            raise ValidationException("El nombre de la etapa es requerido")

        if not data.get('orden'):
            raise ValidationException("El orden de la etapa es requerido")

        # Validar fechas
        if 'fecha_inicio_estimada' in data and 'fecha_fin_estimada' in data:
            if data['fecha_inicio_estimada'] and data['fecha_fin_estimada']:
                if data['fecha_inicio_estimada'] > data['fecha_fin_estimada']:
                    raise ValidationException(
                        "La fecha de inicio no puede ser posterior a la fecha de fin"
                    )

        data['obra_id'] = project_id
        data.setdefault('estado', 'pendiente')
        data.setdefault('progreso', 0)

        try:
            etapa = EtapaObra(**data)
            db.session.add(etapa)
            db.session.commit()
            self._log_info(f"Etapa creada: {etapa.nombre} en proyecto {project_id}")
            return etapa
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al crear etapa: {str(e)}")
            raise ValidationException(f"Error al crear etapa: {str(e)}")

    def update_stage(self, stage_id: int, data: Dict[str, Any]) -> EtapaObra:
        """
        Actualiza una etapa existente.

        Args:
            stage_id: ID de la etapa
            data: Diccionario con los campos a actualizar

        Returns:
            EtapaObra: Instancia de la etapa actualizada

        Raises:
            NotFoundException: Si la etapa no existe
            ValidationException: Si los datos son inválidos
        """
        etapa = EtapaObra.query.get(stage_id)
        if not etapa:
            raise NotFoundException('EtapaObra', stage_id)

        # Validar fechas
        fecha_inicio = data.get('fecha_inicio_estimada', etapa.fecha_inicio_estimada)
        fecha_fin = data.get('fecha_fin_estimada', etapa.fecha_fin_estimada)
        if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
            raise ValidationException(
                "La fecha de inicio no puede ser posterior a la fecha de fin"
            )

        # Validar estado
        if 'estado' in data:
            estados_validos = ['pendiente', 'en_curso', 'finalizada']
            if data['estado'] not in estados_validos:
                raise ValidationException(
                    f"Estado inválido. Debe ser uno de: {', '.join(estados_validos)}"
                )

        try:
            for key, value in data.items():
                if hasattr(etapa, key):
                    setattr(etapa, key, value)
            db.session.commit()
            self._log_info(f"Etapa actualizada: {etapa.nombre} (ID: {stage_id})")
            return etapa
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al actualizar etapa {stage_id}: {str(e)}")
            raise ValidationException(f"Error al actualizar etapa: {str(e)}")

    def delete_stage(self, stage_id: int) -> bool:
        """
        Elimina una etapa y todas sus tareas asociadas.

        Args:
            stage_id: ID de la etapa

        Returns:
            bool: True si se eliminó correctamente

        Raises:
            NotFoundException: Si la etapa no existe
        """
        etapa = EtapaObra.query.get(stage_id)
        if not etapa:
            raise NotFoundException('EtapaObra', stage_id)

        try:
            db.session.delete(etapa)
            db.session.commit()
            self._log_info(f"Etapa eliminada: ID {stage_id}")
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al eliminar etapa {stage_id}: {str(e)}")
            raise ValidationException(f"Error al eliminar etapa: {str(e)}")

    # ===== TASK MANAGEMENT =====

    def create_task(self, etapa_id: int, data: Dict[str, Any]) -> TareaEtapa:
        """
        Crea una nueva tarea en una etapa.

        Args:
            etapa_id: ID de la etapa
            data: Diccionario con los datos de la tarea. Campos requeridos:
                - nombre: Nombre de la tarea
                  Campos opcionales: descripcion, horas_estimadas, responsable_id, etc.

        Returns:
            TareaEtapa: Instancia de la tarea creada

        Raises:
            NotFoundException: Si la etapa no existe
            ValidationException: Si faltan campos requeridos o datos inválidos
        """
        etapa = EtapaObra.query.get(etapa_id)
        if not etapa:
            raise NotFoundException('EtapaObra', etapa_id)

        # Validar campos requeridos
        if not data.get('nombre'):
            raise ValidationException("El nombre de la tarea es requerido")

        # Validar fechas
        if 'fecha_inicio_estimada' in data and 'fecha_fin_estimada' in data:
            if data['fecha_inicio_estimada'] and data['fecha_fin_estimada']:
                if data['fecha_inicio_estimada'] > data['fecha_fin_estimada']:
                    raise ValidationException(
                        "La fecha de inicio no puede ser posterior a la fecha de fin"
                    )

        # Validar responsable si se proporciona
        if 'responsable_id' in data and data['responsable_id']:
            responsable = Usuario.query.get(data['responsable_id'])
            if not responsable:
                raise ValidationException(
                    f"Usuario responsable {data['responsable_id']} no encontrado"
                )

        data['etapa_id'] = etapa_id
        data.setdefault('estado', 'pendiente')
        data.setdefault('horas_reales', Decimal('0'))
        data.setdefault('porcentaje_avance', Decimal('0'))
        data.setdefault('unidad', 'un')

        try:
            tarea = TareaEtapa(**data)
            db.session.add(tarea)
            db.session.commit()
            self._log_info(f"Tarea creada: {tarea.nombre} en etapa {etapa_id}")
            return tarea
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al crear tarea: {str(e)}")
            raise ValidationException(f"Error al crear tarea: {str(e)}")

    def update_task(self, task_id: int, data: Dict[str, Any]) -> TareaEtapa:
        """
        Actualiza una tarea existente.

        Args:
            task_id: ID de la tarea
            data: Diccionario con los campos a actualizar

        Returns:
            TareaEtapa: Instancia de la tarea actualizada

        Raises:
            NotFoundException: Si la tarea no existe
            ValidationException: Si los datos son inválidos
        """
        tarea = TareaEtapa.query.get(task_id)
        if not tarea:
            raise NotFoundException('TareaEtapa', task_id)

        # Validar fechas
        fecha_inicio = data.get('fecha_inicio_estimada', tarea.fecha_inicio_estimada)
        fecha_fin = data.get('fecha_fin_estimada', tarea.fecha_fin_estimada)
        if fecha_inicio and fecha_fin and fecha_inicio > fecha_fin:
            raise ValidationException(
                "La fecha de inicio no puede ser posterior a la fecha de fin"
            )

        # Validar estado
        if 'estado' in data:
            estados_validos = ['pendiente', 'en_curso', 'completada', 'cancelada']
            if data['estado'] not in estados_validos:
                raise ValidationException(
                    f"Estado inválido. Debe ser uno de: {', '.join(estados_validos)}"
                )

            # Establecer fecha de finalización automáticamente si se completa
            if data['estado'] == 'completada' and not tarea.fecha_fin_real:
                data['fecha_fin_real'] = datetime.utcnow()

        # Validar responsable si se actualiza
        if 'responsable_id' in data and data['responsable_id']:
            responsable = Usuario.query.get(data['responsable_id'])
            if not responsable:
                raise ValidationException(
                    f"Usuario responsable {data['responsable_id']} no encontrado"
                )

        try:
            for key, value in data.items():
                if hasattr(tarea, key):
                    setattr(tarea, key, value)
            db.session.commit()
            self._log_info(f"Tarea actualizada: {tarea.nombre} (ID: {task_id})")
            return tarea
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al actualizar tarea {task_id}: {str(e)}")
            raise ValidationException(f"Error al actualizar tarea: {str(e)}")

    def assign_task(self, task_id: int, user_id: int, cuota_objetivo: Optional[Decimal] = None) -> TareaMiembro:
        """
        Asigna un usuario a una tarea.

        Args:
            task_id: ID de la tarea
            user_id: ID del usuario a asignar
            cuota_objetivo: Cuota objetivo opcional para el usuario

        Returns:
            TareaMiembro: Instancia de la asignación

        Raises:
            NotFoundException: Si la tarea o usuario no existe
            ValidationException: Si el usuario ya está asignado
        """
        tarea = TareaEtapa.query.get(task_id)
        if not tarea:
            raise NotFoundException('TareaEtapa', task_id)

        usuario = Usuario.query.get(user_id)
        if not usuario:
            raise NotFoundException('Usuario', user_id)

        # Verificar si ya existe la asignación
        asignacion_existente = TareaMiembro.query.filter_by(
            tarea_id=task_id,
            user_id=user_id
        ).first()

        if asignacion_existente:
            raise ValidationException(
                f"El usuario {user_id} ya está asignado a esta tarea"
            )

        try:
            asignacion = TareaMiembro(
                tarea_id=task_id,
                user_id=user_id,
                cuota_objetivo=cuota_objetivo
            )
            db.session.add(asignacion)
            db.session.commit()
            self._log_info(f"Usuario {user_id} asignado a tarea {task_id}")
            return asignacion
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al asignar usuario a tarea: {str(e)}")
            raise ValidationException(f"Error al asignar usuario: {str(e)}")

    def unassign_task(self, task_id: int, user_id: int) -> bool:
        """
        Desasigna un usuario de una tarea.

        Args:
            task_id: ID de la tarea
            user_id: ID del usuario a desasignar

        Returns:
            bool: True si se desasignó correctamente

        Raises:
            NotFoundException: Si la asignación no existe
        """
        asignacion = TareaMiembro.query.filter_by(
            tarea_id=task_id,
            user_id=user_id
        ).first()

        if not asignacion:
            raise NotFoundException('TareaMiembro', f"tarea_id={task_id}, user_id={user_id}")

        try:
            db.session.delete(asignacion)
            db.session.commit()
            self._log_info(f"Usuario {user_id} desasignado de tarea {task_id}")
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al desasignar usuario: {str(e)}")
            raise ValidationException(f"Error al desasignar usuario: {str(e)}")

    def get_task_summary(self, task_id: int) -> Dict[str, Any]:
        """
        Obtiene un resumen de métricas de una tarea.

        Extrae la lógica de resumen_tarea() con mejoras.

        Args:
            task_id: ID de la tarea

        Returns:
            dict: Diccionario con métricas:
                - plan: Cantidad planificada
                - ejec: Cantidad ejecutada (solo avances aprobados)
                - pct: Porcentaje completado
                - restante: Cantidad restante
                - atrasada: Si la tarea está atrasada
                - estado: Estado de la tarea
                - horas_estimadas: Horas estimadas
                - horas_reales: Horas trabajadas

        Raises:
            NotFoundException: Si la tarea no existe
        """
        tarea = TareaEtapa.query.get(task_id)
        if not tarea:
            raise NotFoundException('TareaEtapa', task_id)

        plan = float(tarea.cantidad_planificada or 0)

        # Suma solo avances aprobados
        ejec = float(
            db.session.query(func.coalesce(func.sum(TareaAvance.cantidad), 0))
            .filter(TareaAvance.tarea_id == task_id, TareaAvance.status == "aprobado")
            .scalar() or 0
        )

        pct = (ejec / plan * 100.0) if plan > 0 else 0.0
        restante = max(plan - ejec, 0.0)
        atrasada = bool(
            tarea.fecha_fin_plan and
            date.today() > tarea.fecha_fin_plan and
            restante > 0
        )

        return {
            "plan": plan,
            "ejec": ejec,
            "pct": round(pct, 2),
            "restante": restante,
            "atrasada": atrasada,
            "estado": tarea.estado,
            "horas_estimadas": float(tarea.horas_estimadas or 0),
            "horas_reales": float(tarea.horas_reales or 0),
            "unidad": tarea.unidad,
            "nombre": tarea.nombre
        }

    # ===== PROGRESS TRACKING =====

    def record_progress(self, task_id: int, data: Dict[str, Any]) -> TareaAvance:
        """
        Registra un avance en una tarea.

        Args:
            task_id: ID de la tarea
            data: Diccionario con los datos del avance. Campos requeridos:
                - cantidad: Cantidad de avance
                - user_id: ID del usuario que registra el avance
                  Campos opcionales: fecha, unidad, horas, notas

        Returns:
            TareaAvance: Instancia del avance creado

        Raises:
            NotFoundException: Si la tarea no existe
            ValidationException: Si faltan campos requeridos o datos inválidos
        """
        tarea = TareaEtapa.query.get(task_id)
        if not tarea:
            raise NotFoundException('TareaEtapa', task_id)

        # Validar campos requeridos
        if 'cantidad' not in data or data['cantidad'] is None:
            raise ValidationException("La cantidad de avance es requerida")

        if 'user_id' not in data:
            raise ValidationException("El ID del usuario es requerido")

        # Validar usuario
        usuario = Usuario.query.get(data['user_id'])
        if not usuario:
            raise ValidationException(f"Usuario {data['user_id']} no encontrado")

        # Validar cantidad
        try:
            cantidad = Decimal(str(data['cantidad']))
            if cantidad <= 0:
                raise ValidationException("La cantidad debe ser mayor a cero")
        except (ValueError, TypeError):
            raise ValidationException("Cantidad inválida")

        data['tarea_id'] = task_id
        data['cantidad'] = cantidad
        data.setdefault('fecha', date.today())
        data.setdefault('unidad', tarea.unidad)
        data.setdefault('status', 'pendiente')

        # Guardar valores originales para auditoría
        data['cantidad_ingresada'] = cantidad
        data['unidad_ingresada'] = data.get('unidad', tarea.unidad)

        try:
            avance = TareaAvance(**data)
            db.session.add(avance)
            db.session.commit()
            self._log_info(
                f"Avance registrado: {cantidad} {data['unidad']} en tarea {task_id} por usuario {data['user_id']}"
            )
            return avance
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al registrar avance: {str(e)}")
            raise ValidationException(f"Error al registrar avance: {str(e)}")

    def approve_progress(self, avance_id: int, user_id: int) -> TareaAvance:
        """
        Aprueba un avance de tarea.

        Args:
            avance_id: ID del avance
            user_id: ID del usuario que aprueba

        Returns:
            TareaAvance: Instancia del avance aprobado

        Raises:
            NotFoundException: Si el avance no existe
            ValidationException: Si el avance ya fue procesado
        """
        avance = TareaAvance.query.get(avance_id)
        if not avance:
            raise NotFoundException('TareaAvance', avance_id)

        if avance.status != 'pendiente':
            raise ValidationException(
                f"El avance ya fue {avance.status}"
            )

        # Validar usuario aprobador
        usuario = Usuario.query.get(user_id)
        if not usuario:
            raise ValidationException(f"Usuario {user_id} no encontrado")

        try:
            avance.status = 'aprobado'
            avance.confirmed_by = user_id
            avance.confirmed_at = datetime.utcnow()
            db.session.commit()
            self._log_info(f"Avance {avance_id} aprobado por usuario {user_id}")

            # Actualizar progreso de la tarea
            tarea = avance.tarea
            if tarea and tarea.cantidad_planificada:
                total_aprobado = (
                    db.session.query(func.coalesce(func.sum(TareaAvance.cantidad), 0))
                    .filter(
                        TareaAvance.tarea_id == tarea.id,
                        TareaAvance.status == 'aprobado'
                    )
                    .scalar() or 0
                )
                porcentaje = min(
                    100,
                    (float(total_aprobado) / float(tarea.cantidad_planificada)) * 100
                )
                tarea.porcentaje_avance = Decimal(str(porcentaje))
                db.session.commit()

            return avance
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al aprobar avance: {str(e)}")
            raise ValidationException(f"Error al aprobar avance: {str(e)}")

    def reject_progress(self, avance_id: int, user_id: int, reason: str) -> TareaAvance:
        """
        Rechaza un avance de tarea.

        Args:
            avance_id: ID del avance
            user_id: ID del usuario que rechaza
            reason: Motivo del rechazo

        Returns:
            TareaAvance: Instancia del avance rechazado

        Raises:
            NotFoundException: Si el avance no existe
            ValidationException: Si el avance ya fue procesado o falta el motivo
        """
        avance = TareaAvance.query.get(avance_id)
        if not avance:
            raise NotFoundException('TareaAvance', avance_id)

        if avance.status != 'pendiente':
            raise ValidationException(
                f"El avance ya fue {avance.status}"
            )

        if not reason or not reason.strip():
            raise ValidationException("El motivo del rechazo es requerido")

        # Validar usuario que rechaza
        usuario = Usuario.query.get(user_id)
        if not usuario:
            raise ValidationException(f"Usuario {user_id} no encontrado")

        try:
            avance.status = 'rechazado'
            avance.confirmed_by = user_id
            avance.confirmed_at = datetime.utcnow()
            avance.reject_reason = reason
            db.session.commit()
            self._log_info(f"Avance {avance_id} rechazado por usuario {user_id}")
            return avance
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al rechazar avance: {str(e)}")
            raise ValidationException(f"Error al rechazar avance: {str(e)}")

    # ===== EVM CALCULATIONS =====

    def calculate_evm_metrics(self, task_id: int, as_of_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Calcula métricas EVM (Earned Value Management) para una tarea.

        Args:
            task_id: ID de la tarea
            as_of_date: Fecha de corte para el cálculo (por defecto: hoy)

        Returns:
            dict: Diccionario con métricas EVM:
                - pv: Planned Value (Valor Planificado)
                - ev: Earned Value (Valor Ganado)
                - ac: Actual Cost (Costo Real)
                - sv: Schedule Variance (SV = EV - PV)
                - cv: Cost Variance (CV = EV - AC)
                - spi: Schedule Performance Index (SPI = EV / PV)
                - cpi: Cost Performance Index (CPI = EV / AC)

        Raises:
            NotFoundException: Si la tarea no existe
        """
        tarea = TareaEtapa.query.get(task_id)
        if not tarea:
            raise NotFoundException('TareaEtapa', task_id)

        if not as_of_date:
            as_of_date = date.today()

        # Calcular PV (Planned Value) - suma de pv_mo hasta la fecha
        pv = float(
            db.session.query(func.coalesce(func.sum(TareaPlanSemanal.pv_mo), 0))
            .filter(
                TareaPlanSemanal.tarea_id == task_id,
                TareaPlanSemanal.semana <= as_of_date
            )
            .scalar() or 0
        )

        # Calcular AC (Actual Cost) - suma de ac_mo hasta la fecha
        ac = float(
            db.session.query(func.coalesce(func.sum(TareaAvanceSemanal.ac_mo), 0))
            .filter(
                TareaAvanceSemanal.tarea_id == task_id,
                TareaAvanceSemanal.semana <= as_of_date
            )
            .scalar() or 0
        )

        # Calcular EV (Earned Value) - suma de ev_mo hasta la fecha
        ev = float(
            db.session.query(func.coalesce(func.sum(TareaAvanceSemanal.ev_mo), 0))
            .filter(
                TareaAvanceSemanal.tarea_id == task_id,
                TareaAvanceSemanal.semana <= as_of_date
            )
            .scalar() or 0
        )

        # Calcular varianzas
        sv = ev - pv  # Schedule Variance
        cv = ev - ac  # Cost Variance

        # Calcular índices de desempeño
        spi = (ev / pv) if pv > 0 else 0  # Schedule Performance Index
        cpi = (ev / ac) if ac > 0 else 0  # Cost Performance Index

        return {
            'pv': round(pv, 2),
            'ev': round(ev, 2),
            'ac': round(ac, 2),
            'sv': round(sv, 2),
            'cv': round(cv, 2),
            'spi': round(spi, 4),
            'cpi': round(cpi, 4),
            'fecha_corte': as_of_date.isoformat(),
            'interpretacion': {
                'schedule_status': 'adelantado' if sv > 0 else 'atrasado' if sv < 0 else 'en tiempo',
                'cost_status': 'bajo presupuesto' if cv > 0 else 'sobre presupuesto' if cv < 0 else 'en presupuesto',
                'schedule_efficiency': 'eficiente' if spi > 1 else 'ineficiente' if spi < 1 else 'normal',
                'cost_efficiency': 'eficiente' if cpi > 1 else 'ineficiente' if cpi < 1 else 'normal'
            }
        }

    def get_project_metrics(self, project_id: int) -> Dict[str, Any]:
        """
        Obtiene métricas agregadas de un proyecto.

        Args:
            project_id: ID del proyecto

        Returns:
            dict: Diccionario con métricas del proyecto:
                - progreso: Información de progreso
                - presupuesto: Información presupuestaria
                - tiempo: Información temporal
                - tareas: Estadísticas de tareas
                - etapas: Estadísticas de etapas

        Raises:
            NotFoundException: Si el proyecto no existe
        """
        obra = self.get_by_id_or_fail(project_id)

        # Calcular progreso
        progreso_info = self.calculate_progress(project_id, auto_update=False)

        # Estadísticas de etapas
        total_etapas = obra.etapas.count()
        etapas_finalizadas = obra.etapas.filter_by(estado='finalizada').count()
        etapas_en_curso = obra.etapas.filter_by(estado='en_curso').count()

        # Estadísticas de tareas
        tareas = TareaEtapa.query.join(EtapaObra).filter(
            EtapaObra.obra_id == project_id
        )
        total_tareas = tareas.count()
        tareas_completadas = tareas.filter_by(estado='completada').count()
        tareas_en_curso = tareas.filter_by(estado='en_curso').count()
        tareas_pendientes = tareas.filter_by(estado='pendiente').count()

        # Información presupuestaria
        presupuesto = float(obra.presupuesto_total or 0)
        costo_real = float(obra.costo_real or 0)
        porcentaje_ejecutado = obra.porcentaje_presupuesto_ejecutado

        # Información temporal
        dias_transcurridos = obra.dias_transcurridos
        dias_restantes = obra.dias_restantes

        return {
            'progreso': {
                'total': progreso_info['progreso_total'],
                'etapas': progreso_info['progreso_etapas'],
                'certificaciones': progreso_info['progreso_certificaciones']
            },
            'presupuesto': {
                'total': presupuesto,
                'ejecutado': costo_real,
                'porcentaje_ejecutado': round(porcentaje_ejecutado, 2),
                'disponible': presupuesto - costo_real
            },
            'tiempo': {
                'dias_transcurridos': dias_transcurridos,
                'dias_restantes': dias_restantes,
                'fecha_inicio': obra.fecha_inicio.isoformat() if obra.fecha_inicio else None,
                'fecha_fin_estimada': obra.fecha_fin_estimada.isoformat() if obra.fecha_fin_estimada else None
            },
            'etapas': {
                'total': total_etapas,
                'finalizadas': etapas_finalizadas,
                'en_curso': etapas_en_curso,
                'pendientes': total_etapas - etapas_finalizadas - etapas_en_curso
            },
            'tareas': {
                'total': total_tareas,
                'completadas': tareas_completadas,
                'en_curso': tareas_en_curso,
                'pendientes': tareas_pendientes
            },
            'estado': obra.estado
        }

    # ===== PROJECT ASSIGNMENTS =====

    def assign_user_to_project(
        self,
        project_id: int,
        user_id: int,
        role: str,
        etapa_id: Optional[int] = None
    ) -> AsignacionObra:
        """
        Asigna un usuario a un proyecto.

        Args:
            project_id: ID del proyecto
            user_id: ID del usuario
            role: Rol en la obra (jefe_obra, supervisor, operario)
            etapa_id: ID de etapa específica (opcional)

        Returns:
            AsignacionObra: Instancia de la asignación

        Raises:
            NotFoundException: Si el proyecto, usuario o etapa no existe
            ValidationException: Si el rol es inválido o ya existe asignación
        """
        obra = self.get_by_id_or_fail(project_id)

        usuario = Usuario.query.get(user_id)
        if not usuario:
            raise NotFoundException('Usuario', user_id)

        # Validar rol
        roles_validos = ['jefe_obra', 'supervisor', 'operario']
        if role not in roles_validos:
            raise ValidationException(
                f"Rol inválido. Debe ser uno de: {', '.join(roles_validos)}"
            )

        # Validar etapa si se proporciona
        if etapa_id:
            etapa = EtapaObra.query.get(etapa_id)
            if not etapa:
                raise NotFoundException('EtapaObra', etapa_id)
            if etapa.obra_id != project_id:
                raise ValidationException("La etapa no pertenece al proyecto especificado")

        # Verificar si ya existe asignación activa
        asignacion_existente = AsignacionObra.query.filter_by(
            obra_id=project_id,
            usuario_id=user_id,
            etapa_id=etapa_id,
            activo=True
        ).first()

        if asignacion_existente:
            raise ValidationException(
                "Ya existe una asignación activa para este usuario en este proyecto/etapa"
            )

        try:
            asignacion = AsignacionObra(
                obra_id=project_id,
                usuario_id=user_id,
                rol_en_obra=role,
                etapa_id=etapa_id,
                activo=True
            )
            db.session.add(asignacion)
            db.session.commit()
            self._log_info(
                f"Usuario {user_id} asignado al proyecto {project_id} como {role}"
            )
            return asignacion
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al asignar usuario a proyecto: {str(e)}")
            raise ValidationException(f"Error al asignar usuario: {str(e)}")

    def remove_user_from_project(
        self,
        project_id: int,
        user_id: int,
        etapa_id: Optional[int] = None
    ) -> bool:
        """
        Elimina (desactiva) la asignación de un usuario a un proyecto.

        Args:
            project_id: ID del proyecto
            user_id: ID del usuario
            etapa_id: ID de etapa específica (opcional)

        Returns:
            bool: True si se eliminó correctamente

        Raises:
            NotFoundException: Si la asignación no existe
        """
        asignacion = AsignacionObra.query.filter_by(
            obra_id=project_id,
            usuario_id=user_id,
            etapa_id=etapa_id,
            activo=True
        ).first()

        if not asignacion:
            raise NotFoundException(
                'AsignacionObra',
                f"proyecto={project_id}, usuario={user_id}, etapa={etapa_id}"
            )

        try:
            asignacion.activo = False
            db.session.commit()
            self._log_info(
                f"Usuario {user_id} desasignado del proyecto {project_id}"
            )
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            self._log_error(f"Error al desasignar usuario: {str(e)}")
            raise ValidationException(f"Error al desasignar usuario: {str(e)}")

    def get_project_members(self, project_id: int, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Obtiene los miembros asignados a un proyecto.

        Args:
            project_id: ID del proyecto
            active_only: Si True, solo devuelve asignaciones activas

        Returns:
            list: Lista de diccionarios con información de los miembros

        Raises:
            NotFoundException: Si el proyecto no existe
        """
        obra = self.get_by_id_or_fail(project_id)

        query = AsignacionObra.query.filter_by(obra_id=project_id)
        if active_only:
            query = query.filter_by(activo=True)

        asignaciones = query.all()

        miembros = []
        for asignacion in asignaciones:
            miembros.append({
                'asignacion_id': asignacion.id,
                'usuario_id': asignacion.usuario_id,
                'usuario_nombre': asignacion.usuario.nombre if asignacion.usuario else None,
                'usuario_email': asignacion.usuario.email if asignacion.usuario else None,
                'rol_en_obra': asignacion.rol_en_obra,
                'etapa_id': asignacion.etapa_id,
                'etapa_nombre': asignacion.etapa.nombre if asignacion.etapa else None,
                'fecha_asignacion': asignacion.fecha_asignacion.isoformat() if asignacion.fecha_asignacion else None,
                'activo': asignacion.activo
            })

        return miembros
