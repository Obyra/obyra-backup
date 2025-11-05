"""
Servicio compartido para funcionalidades comunes entre obras y presupuestos.

Este módulo centraliza funciones auxiliares, de permisos y lógica de negocio
que anteriormente estaban duplicadas en obras.py y presupuestos.py.
"""
from datetime import datetime, date
from decimal import Decimal
from flask import current_app, request, jsonify
from flask_login import current_user
from pathlib import Path
import uuid
from werkzeug.utils import secure_filename


class ProjectSharedService:
    """Servicio con lógica compartida entre proyectos/obras y presupuestos"""

    # ==== Funciones auxiliares ====

    @staticmethod
    def parse_date(value):
        """
        Parsea una fecha de string a date.

        Soporta formatos: '%Y-%m-%d' y '%d/%m/%Y'

        Args:
            value: String con la fecha a parsear

        Returns:
            date object o None si no puede parsear
        """
        if not value:
            return None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def get_roles_usuario(user):
        """
        Devuelve set normalizado de roles posibles del usuario.

        Considera tanto el atributo .role como .rol para compatibilidad.

        Args:
            user: Objeto usuario

        Returns:
            set: Conjunto de roles en minúsculas
        """
        vals = set()
        for attr in ('role', 'rol'):
            v = getattr(user, attr, None)
            if v:
                vals.add(str(v).lower())
        return vals

    @staticmethod
    def is_admin(user=None):
        """
        Verifica si el usuario es admin.

        Args:
            user: Usuario a verificar (default: current_user)

        Returns:
            bool: True si es admin/administrador
        """
        if user is None:
            user = current_user
        roles = ProjectSharedService.get_roles_usuario(user)
        return any(r in roles for r in ('admin', 'administrador'))

    @staticmethod
    def is_pm_global(user=None):
        """
        Verifica si el usuario es admin, PM global o técnico.

        Args:
            user: Usuario a verificar (default: current_user)

        Returns:
            bool: True si tiene permisos globales de PM
        """
        if user is None:
            user = current_user
        roles = ProjectSharedService.get_roles_usuario(user)
        return any(r in roles for r in ('admin', 'administrador', 'pm', 'project_manager', 'tecnico'))

    # ==== Funciones de permisos ====

    @staticmethod
    def can_manage_obra(obra, user=None):
        """
        Verifica si el usuario puede gestionar la obra.

        Permite crear/editar/gestionar etapas y tareas.

        Args:
            obra: Objeto Obra
            user: Usuario a verificar (default: current_user)

        Returns:
            bool: True si tiene permisos para gestionar
        """
        from models import ObraMiembro

        if user is None:
            user = current_user

        if ProjectSharedService.is_admin(user) or ProjectSharedService.is_pm_global(user):
            return True

        # PM específico de esta obra
        miembro = ObraMiembro.query.filter_by(
            obra_id=obra.id,
            usuario_id=user.id,
            rol_en_obra='pm'
        ).first()
        return miembro is not None

    @staticmethod
    def can_log_avance(tarea, user=None):
        """
        Verifica si el usuario puede registrar avances en una tarea.

        Args:
            tarea: Objeto TareaEtapa
            user: Usuario a verificar (default: current_user)

        Returns:
            bool: True si puede registrar avances
        """
        from models import TareaMiembro

        if user is None:
            user = current_user

        if ProjectSharedService.is_admin(user):
            return True

        roles = ProjectSharedService.get_roles_usuario(user)
        if 'pm' in roles or 'project_manager' in roles or 'tecnico' in roles:
            return True

        if tarea.responsable_id == user.id:
            return True

        miembro = TareaMiembro.query.filter_by(tarea_id=tarea.id, user_id=user.id).first()
        return miembro is not None

    @staticmethod
    def es_miembro_obra(obra_id, user_id):
        """
        Verifica si el usuario es miembro de la obra (cualquier rol).

        Args:
            obra_id: ID de la obra
            user_id: ID del usuario

        Returns:
            bool: True si es miembro
        """
        from models import ObraMiembro, TareaMiembro, TareaEtapa, EtapaObra
        from app import db

        if ProjectSharedService.is_pm_global():
            return True

        miembro = db.session.query(ObraMiembro.id)\
            .filter_by(obra_id=obra_id, usuario_id=user_id).first()
        if miembro:
            return True

        tiene_tareas = (db.session.query(TareaMiembro.id)
                       .join(TareaEtapa, TareaMiembro.tarea_id == TareaEtapa.id)
                       .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)
                       .filter(EtapaObra.obra_id == obra_id,
                               TareaMiembro.user_id == user_id)
                       .first())
        return tiene_tareas is not None

    # ==== Funciones de API duplicadas ====

    @staticmethod
    def api_crear_avance_fotos(tarea_id, normalize_unit_func, recalc_tarea_pct_func):
        """
        Crea un avance con fotos para una tarea.

        Esta función maneja toda la lógica de:
        - Validación de permisos
        - Procesamiento del formulario
        - Creación del avance
        - Guardado de fotos
        - Actualización de métricas

        Args:
            tarea_id: ID de la tarea
            normalize_unit_func: Función para normalizar unidades
            recalc_tarea_pct_func: Función para recalcular porcentajes

        Returns:
            JSON response con resultado de la operación
        """
        from models import TareaEtapa, TareaAvance, TareaAvanceFoto
        from app import db

        tarea = TareaEtapa.query.get_or_404(tarea_id)

        if not ProjectSharedService.can_log_avance(tarea):
            return jsonify(ok=False, error="Sin permisos para registrar avance en esta tarea"), 403

        roles = ProjectSharedService.get_roles_usuario(current_user)
        if 'operario' in roles:
            from_dashboard = request.headers.get('X-From-Dashboard') == '1'
            if not from_dashboard:
                return jsonify(ok=False, error="Los operarios solo pueden registrar avances desde su dashboard"), 403

        if tarea.etapa.obra.organizacion_id != current_user.organizacion_id:
            return jsonify(ok=False, error="Sin permiso"), 403

        cantidad_str = str(request.form.get("cantidad_ingresada", "")).replace(",", ".")
        try:
            cantidad = float(cantidad_str)
            if cantidad <= 0:
                return jsonify(ok=False, error="La cantidad debe ser mayor a 0"), 400
        except (ValueError, TypeError):
            return jsonify(ok=False, error="Cantidad inválida"), 400

        unidad_servidor = normalize_unit_func(tarea.unidad)
        horas_trabajadas = request.form.get("horas_trabajadas", type=float)
        notas = request.form.get("nota", "")

        try:
            avance = TareaAvance(
                tarea_id=tarea.id,
                user_id=current_user.id,
                cantidad=cantidad,
                unidad=unidad_servidor,
                horas=horas_trabajadas,
                notas=notas,
                cantidad_ingresada=cantidad,
                unidad_ingresada=unidad_servidor,
                horas_trabajadas=horas_trabajadas
            )

            if roles & {'administrador', 'tecnico', 'admin', 'pm', 'project_manager'}:
                avance.status = "aprobado"
                avance.confirmed_by = current_user.id
                avance.confirmed_at = datetime.utcnow()

            db.session.add(avance)
            db.session.flush()

            if not tarea.fecha_inicio_real and avance.status == "aprobado":
                tarea.fecha_inicio_real = datetime.utcnow()

            media_base = Path(current_app.instance_path) / "media"
            media_base.mkdir(exist_ok=True)

            uploaded_files = request.files.getlist("fotos")
            for foto_file in uploaded_files:
                if foto_file.filename:
                    extension = Path(foto_file.filename).suffix.lower()
                    unique_name = f"{uuid.uuid4()}{extension}"

                    avance_dir = media_base / "avances" / str(avance.id)
                    avance_dir.mkdir(parents=True, exist_ok=True)

                    file_path = avance_dir / unique_name
                    foto_file.save(file_path)

                    width, height = None, None
                    try:
                        from PIL import Image
                        with Image.open(file_path) as img:
                            width, height = img.size
                    except Exception:
                        pass

                    relative_path = f"avances/{avance.id}/{unique_name}"
                    foto = TareaAvanceFoto(
                        avance_id=avance.id,
                        file_path=relative_path,
                        mime_type=foto_file.content_type,
                        width=width,
                        height=height
                    )
                    db.session.add(foto)

            db.session.commit()

            recalc_tarea_pct_func(tarea.id)

            return jsonify(ok=True, avance_id=avance.id, porcentaje_actualizado=tarea.porcentaje_avance)

        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error creating progress with photos")
            return jsonify(ok=False, error="Error interno del servidor"), 500

    @staticmethod
    def historial_certificaciones(
        obra_id,
        blueprint_name,
        create_certification_func,
        certification_totals_func,
        build_pending_entries_func,
        approved_entries_func,
        pending_percentage_func,
        resolve_budget_context_func,
        register_payment_func=None
    ):
        """
        Maneja el historial de certificaciones de una obra.

        Soporta GET (visualización) y POST (creación/actualización).

        Args:
            obra_id: ID de la obra
            blueprint_name: Nombre del blueprint ('obras' o 'presupuestos')
            create_certification_func: Función para crear certificaciones
            certification_totals_func: Función para calcular totales
            build_pending_entries_func: Función para certificaciones pendientes
            approved_entries_func: Función para certificaciones aprobadas
            pending_percentage_func: Función para calcular porcentajes
            resolve_budget_context_func: Función para resolver contexto presupuestario
            register_payment_func: Función para registrar pagos (opcional)

        Returns:
            Response apropiada (template o JSON)
        """
        from models import Obra, WorkCertification
        from app import db
        from flask import render_template, flash, redirect, url_for
        from services.memberships import get_current_org_id, get_current_membership

        obra = Obra.query.filter_by(id=obra_id, organizacion_id=get_current_org_id()).first_or_404()
        membership = get_current_membership()

        if request.method == 'POST':
            payload = request.get_json(silent=True) or request.form
            if not membership or membership.role not in ('admin', 'project_manager'):
                error_msg = 'No tienes permisos para crear certificaciones.'
                if request.is_json:
                    return jsonify(ok=False, error=error_msg), 403
                flash(error_msg, 'danger')
                return redirect(url_for(f'{blueprint_name}.historial_certificaciones', id=obra_id))

            cert_id = payload.get('certificacion_id')
            periodo = (
                ProjectSharedService.parse_date(payload.get('periodo_desde')),
                ProjectSharedService.parse_date(payload.get('periodo_hasta')),
            )
            aprobar_flag = str(payload.get('aprobar', 'true')).lower() in {'1', 'true', 'yes', 'y', 'on'}
            notas = payload.get('notas')

            try:
                if cert_id:
                    cert = WorkCertification.query.get_or_404(int(cert_id))
                    if cert.obra_id != obra.id:
                        from flask import abort
                        abort(404)
                    if payload.get('porcentaje'):
                        cert.porcentaje_avance = Decimal(str(payload['porcentaje']).replace(',', '.'))
                    if aprobar_flag and cert.estado != 'aprobada':
                        cert.marcar_aprobada(current_user)
                    if periodo[0] or periodo[1]:
                        cert.periodo_desde, cert.periodo_hasta = periodo
                    if notas is not None:
                        cert.notas = notas
                    db.session.commit()
                    response = {'ok': True, 'certificacion_id': cert.id, 'estado': cert.estado}
                    if request.is_json:
                        return jsonify(response)
                    flash('Certificación actualizada correctamente.', 'success')
                    return redirect(url_for(f'{blueprint_name}.historial_certificaciones', id=obra_id))

                porcentaje_raw = payload.get('porcentaje') or payload.get('porcentaje_avance')
                if not porcentaje_raw:
                    raise ValueError('Debes indicar el porcentaje de avance a certificar.')

                porcentaje = Decimal(str(porcentaje_raw).replace(',', '.'))
                cert = create_certification_func(
                    obra,
                    current_user,
                    porcentaje,
                    periodo=periodo,
                    notas=notas,
                    aprobar=aprobar_flag,
                    fuente=payload.get('fuente', 'tareas'),
                )
                db.session.commit()
                response = {'ok': True, 'certificacion_id': cert.id, 'estado': cert.estado}
                if request.is_json:
                    return jsonify(response)
                flash('Certificación creada correctamente.', 'success')
                return redirect(url_for(f'{blueprint_name}.historial_certificaciones', id=obra_id))
            except Exception as exc:
                db.session.rollback()
                if request.is_json:
                    return jsonify(ok=False, error=str(exc)), 400
                flash(f'Error al crear la certificación: {exc}', 'danger')
                return redirect(url_for(f'{blueprint_name}.historial_certificaciones', id=obra_id))

        resumen = certification_totals_func(obra)
        pendientes = build_pending_entries_func(obra)
        aprobadas = approved_entries_func(obra)
        pct_aprobado, pct_borrador, pct_sugerido = pending_percentage_func(obra)
        context = resolve_budget_context_func(obra)
        puede_aprobar = membership and membership.role in ('admin', 'project_manager')

        if request.args.get('format') == 'json':
            return jsonify(
                ok=True,
                resumen={k: str(v) for k, v in resumen.items()},
                pendientes=[
                    {**row, 'porcentaje': str(row['porcentaje']), 'monto_ars': str(row['monto_ars']), 'monto_usd': str(row['monto_usd'])}
                    for row in pendientes
                ],
                aprobadas=[
                    {
                        **row,
                        'porcentaje': str(row['porcentaje']),
                        'monto_ars': str(row['monto_ars']),
                        'monto_usd': str(row['monto_usd']),
                        'pagado_ars': str(row['pagado_ars']),
                        'pagado_usd': str(row['pagado_usd']),
                        'saldo_ars': str(row['saldo_ars']),
                        'saldo_usd': str(row['saldo_usd']),
                    }
                    for row in aprobadas
                ],
                porcentajes={
                    'aprobado': str(pct_aprobado),
                    'borrador': str(pct_borrador),
                    'sugerido': str(pct_sugerido),
                },
            )

        return render_template(
            'obras/certificaciones.html',
            obra=obra,
            pendientes=pendientes,
            certificaciones_aprobadas=aprobadas,
            resumen=resumen,
            porcentajes=(pct_aprobado, pct_borrador, pct_sugerido),
            puede_aprobar=bool(puede_aprobar),
            contexto=context,
        )

    @staticmethod
    def wizard_crear_tareas(obra_id):
        """
        Wizard para creación masiva de tareas y asignación de miembros.

        Permite crear múltiples tareas en diferentes etapas en una sola operación,
        con validación de duplicados y asignación automática de responsables.

        Args:
            obra_id: ID de la obra

        Returns:
            JSON response con estadísticas de creación
        """
        from models import Obra, EtapaObra, TareaEtapa, ObraMiembro, TareaMiembro
        from app import db

        obra = Obra.query.get_or_404(obra_id)
        if not ProjectSharedService.can_manage_obra(obra):
            return jsonify(ok=False, error="Sin permisos para gestionar esta obra"), 403

        try:
            data = request.get_json()
            if not data:
                return jsonify(ok=False, error="JSON requerido"), 400

            etapas_data = data.get('etapas', [])
            evitar_duplicados = data.get('evitar_duplicados', True)

            if not etapas_data:
                return jsonify(ok=False, error="Se requiere al menos una etapa"), 400

            creadas = 0
            ya_existian = 0
            asignaciones_creadas = 0

            db.session.begin()
            current_app.logger.info(f"WIZARD: Creando tareas para obra {obra_id}")

            for etapa_data in etapas_data:
                etapa_id = etapa_data.get('etapa_id')
                tareas_data = etapa_data.get('tareas', [])

                etapa = EtapaObra.query.filter_by(id=etapa_id, obra_id=obra_id).first()
                if not etapa:
                    db.session.rollback()
                    return jsonify(ok=False, error=f"Etapa {etapa_id} no existe en esta obra"), 400

                for tarea_data in tareas_data:
                    nombre = tarea_data.get('nombre')
                    inicio = tarea_data.get('inicio')
                    fin = tarea_data.get('fin')
                    horas_estimadas = tarea_data.get('horas_estimadas')
                    unidad = tarea_data.get('unidad', 'h')
                    responsable_id = tarea_data.get('responsable_id')

                    if not nombre:
                        db.session.rollback()
                        return jsonify(ok=False, error="Nombre de tarea requerido"), 400

                    if responsable_id:
                        miembro = ObraMiembro.query.filter_by(obra_id=obra_id, usuario_id=responsable_id).first()
                        if not miembro:
                            db.session.rollback()
                            return jsonify(ok=False, error=f"Usuario {responsable_id} no es miembro de esta obra"), 400

                    fecha_inicio_plan = None
                    fecha_fin_plan = None

                    if inicio:
                        try:
                            fecha_inicio_plan = datetime.strptime(inicio, '%Y-%m-%d').date()
                        except ValueError:
                            db.session.rollback()
                            return jsonify(ok=False, error=f"Fecha inicio inválida: {inicio}"), 400

                    if fin:
                        try:
                            fecha_fin_plan = datetime.strptime(fin, '%Y-%m-%d').date()
                        except ValueError:
                            db.session.rollback()
                            return jsonify(ok=False, error=f"Fecha fin inválida: {fin}"), 400

                    tarea_existente = None
                    if evitar_duplicados:
                        tarea_existente = TareaEtapa.query.filter_by(etapa_id=etapa_id, nombre=nombre).first()

                    if tarea_existente:
                        ya_existian += 1
                        tarea = tarea_existente
                        if fecha_inicio_plan:
                            tarea.fecha_inicio_plan = fecha_inicio_plan
                        if fecha_fin_plan:
                            tarea.fecha_fin_plan = fecha_fin_plan
                        if horas_estimadas:
                            tarea.horas_estimadas = horas_estimadas
                        if unidad:
                            tarea.unidad = unidad
                        if responsable_id:
                            tarea.responsable_id = responsable_id
                    else:
                        tarea = TareaEtapa(
                            etapa_id=etapa_id,
                            nombre=nombre,
                            descripcion="Creada via wizard",
                            estado='pendiente',
                            fecha_inicio_plan=fecha_inicio_plan,
                            fecha_fin_plan=fecha_fin_plan,
                            horas_estimadas=horas_estimadas,
                            unidad=unidad,
                            responsable_id=responsable_id
                        )
                        db.session.add(tarea)
                        db.session.flush()
                        creadas += 1

                    if responsable_id:
                        asignacion_existente = TareaMiembro.query.filter_by(
                            tarea_id=tarea.id, user_id=responsable_id
                        ).first()
                        if not asignacion_existente:
                            asignacion = TareaMiembro(tarea_id=tarea.id, user_id=responsable_id, cuota_objetivo=None)
                            db.session.add(asignacion)
                            asignaciones_creadas += 1

            db.session.commit()

            return jsonify(ok=True, creadas=creadas, ya_existian=ya_existian, asignaciones_creadas=asignaciones_creadas)

        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("WIZARD: Error creando tareas")
            return jsonify(ok=False, error=f"Error interno: {str(e)}"), 500
