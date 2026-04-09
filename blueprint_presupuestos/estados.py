"""
State management + conversion routes: confirmar_como_obra, editar_obra, eliminar,
cambiar_estado, revertir_borrador, restaurar, asignar_cliente, crear_asignar_cliente,
revertir_confirmacion_obra, guardar_presupuesto
"""
import json
from datetime import date
from decimal import Decimal

from flask import (request, flash, redirect, url_for, jsonify, current_app)
from flask_login import login_required, current_user

from extensions import db, limiter
from models import Presupuesto, ItemPresupuesto, Obra, Cliente
from services.calculation import BudgetCalculator, BudgetConstants
from services.memberships import get_current_org_id
from services.plan_service import require_active_subscription

from blueprint_presupuestos import presupuestos_bp, identificar_etapa_por_tipo


@presupuestos_bp.route('/<int:id>/confirmar-obra', methods=['POST'])
@login_required
@require_active_subscription
def confirmar_como_obra(id):
    """Confirmar presupuesto y convertirlo en obra"""
    try:
        org_id = get_current_org_id()
        presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

        # Solo administradores pueden confirmar presupuestos
        if not current_user.es_admin():
            return jsonify({'error': '⛔ Solo administradores pueden confirmar presupuestos como obras. Contactá a tu administrador.'}), 403

        # Verificar que el presupuesto no esté ya confirmado
        if presupuesto.confirmado_como_obra:
            return jsonify({'error': '❌ Este presupuesto ya fue confirmado como obra. No se puede confirmar dos veces.'}), 400

        # Verificar que tenga ítems
        if presupuesto.items.count() == 0:
            return jsonify({'error': '❌ No se puede confirmar un presupuesto sin ítems. Agregá al menos un ítem o usá la calculadora IA primero.'}), 400

        # Verificar límite de obras del plan
        from obras.core import verificar_limite_obras
        puede_crear, mensaje_obras = verificar_limite_obras(org_id)
        if not puede_crear:
            return jsonify({'error': f'❌ {mensaje_obras}'}), 400

        # Obtener datos del formulario
        data = request.get_json() or {}
        crear_tareas = data.get('crear_tareas', True)
        normalizar_slugs = data.get('normalizar_slugs', True)

        # Crear la obra desde el presupuesto
        obra = Obra()

        # Datos básicos de la obra
        # Extraer el nombre del JSON datos_proyecto si existe
        nombre_obra = f"Obra {presupuesto.numero}"
        if presupuesto.datos_proyecto:
            try:
                proyecto_data = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
                nombre_obra = proyecto_data.get('nombre_obra') or proyecto_data.get('nombre') or nombre_obra
            except (json.JSONDecodeError, TypeError):
                pass

        obra.nombre = nombre_obra[:200]  # Limitar a 200 caracteres
        obra.organizacion_id = presupuesto.organizacion_id

        # Cliente
        if presupuesto.cliente:
            obra.cliente_id = presupuesto.cliente_id
            obra.cliente = presupuesto.cliente.nombre_completo
            obra.telefono_cliente = presupuesto.cliente.telefono
            obra.email_cliente = presupuesto.cliente.email
        else:
            obra.cliente = "Sin cliente asignado"

        # Ubicación
        obra.direccion = presupuesto.ubicacion_texto
        obra.direccion_normalizada = presupuesto.ubicacion_normalizada
        obra.latitud = presupuesto.geo_latitud
        obra.longitud = presupuesto.geo_longitud
        obra.geocode_place_id = presupuesto.geocode_place_id
        obra.geocode_provider = presupuesto.geocode_provider
        obra.geocode_status = presupuesto.geocode_status
        obra.geocode_raw = presupuesto.geocode_raw
        obra.geocode_actualizado = presupuesto.geocode_actualizado

        # Si la geocodificacion del presupuesto quedo pendiente, intentar ahora
        if (not obra.latitud or not obra.longitud) and obra.direccion:
            try:
                from services.geocoding_service import geocode_address
                geo_result = geocode_address(obra.direccion)
                if geo_result and geo_result.get('lat') and geo_result.get('lng'):
                    obra.latitud = geo_result['lat']
                    obra.longitud = geo_result['lng']
                    obra.geocode_status = 'ok'
                    obra.geocode_provider = geo_result.get('provider', 'unknown')
                    obra.direccion_normalizada = geo_result.get('formatted_address') or obra.direccion
                    current_app.logger.info(f"Geocodificacion exitosa al confirmar presupuesto: {obra.direccion}")
            except Exception as geo_err:
                current_app.logger.warning(f"Geocodificacion fallo al confirmar: {geo_err}")

        # Presupuesto y fechas
        obra.presupuesto_total = presupuesto.total_con_iva
        obra.fecha_inicio = date.today()
        obra.fecha_fin_estimada = presupuesto.fecha_vigencia
        obra.estado = 'planificacion'
        obra.progreso = 0

        db.session.add(obra)
        db.session.flush()  # Para obtener el ID de la obra

        # Marcar el presupuesto como confirmado
        presupuesto.confirmado_como_obra = True
        presupuesto.obra_id = obra.id
        presupuesto.estado = 'aprobado'

        # SIEMPRE crear/asociar etapas del presupuesto a la obra automáticamente
        from models.budgets import ItemPresupuesto
        from models.projects import EtapaObra, TareaEtapa

        # Obtener todos los ítems del presupuesto
        items = db.session.query(ItemPresupuesto).filter(
            ItemPresupuesto.presupuesto_id == presupuesto.id
        ).order_by(ItemPresupuesto.etapa_id, ItemPresupuesto.tipo).all()

        # Verificar si hay payload de IA guardado en datos_proyecto
        ia_payload = None
        if presupuesto.datos_proyecto:
            try:
                proyecto_data = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
                ia_payload = proyecto_data.get('ia_payload')
                if ia_payload:
                    current_app.logger.info(f"📌 Payload de IA encontrado para presupuesto {presupuesto.numero}, creando etapas desde IA")
            except (json.JSONDecodeError, TypeError) as e:
                current_app.logger.error(f"Error parseando datos_proyecto: {str(e)}")

        # Agrupar ítems por etapa
        etapas_dict = {}
        etapas_obj_map = {}  # Para mapear nombre -> objeto EtapaObra

        if ia_payload and ia_payload.get('etapas'):
            # Usar el payload de IA para crear etapas
            etapas_ia = ia_payload.get('etapas', [])
            items_list = list(items)  # Convertir a lista para iterar
            item_index = 0

            for orden, etapa_ia in enumerate(etapas_ia, start=1):
                etapa_nombre = etapa_ia.get('nombre', f'Etapa {orden}')
                num_items_etapa = len(etapa_ia.get('items', []))

                # Crear EtapaObra
                etapa_obj = EtapaObra(
                    obra_id=obra.id,
                    nombre=etapa_nombre,
                    orden=orden,
                    estado='pendiente',
                    progreso=0
                )
                db.session.add(etapa_obj)
                db.session.flush()  # Para obtener el ID

                etapas_obj_map[etapa_nombre] = etapa_obj
                etapas_dict[etapa_nombre] = []

                current_app.logger.info(f"📌 Creada etapa '{etapa_nombre}' (ID: {etapa_obj.id}) para obra {obra.id}")

                # Asignar items a esta etapa
                for _ in range(num_items_etapa):
                    if item_index < len(items_list):
                        item = items_list[item_index]
                        item.etapa_id = etapa_obj.id
                        etapas_dict[etapa_nombre].append(item)
                        item_index += 1
                        current_app.logger.info(f"📌 Item '{item.descripcion}' asignado a etapa '{etapa_nombre}' (ID: {etapa_obj.id})")

        else:
            # Fallback: agrupar por identificación automática
            for item in items:
                if item.etapa_id and item.etapa:
                    etapa_nombre = item.etapa.nombre
                    etapa_obj = item.etapa
                else:
                    etapa_nombre = identificar_etapa_por_tipo(item)
                    etapa_obj = None

                if etapa_nombre not in etapas_dict:
                    etapas_dict[etapa_nombre] = []
                    if etapa_obj:
                        etapas_obj_map[etapa_nombre] = etapa_obj

                etapas_dict[etapa_nombre].append(item)

        # Crear/asociar todas las etapas a la obra
        orden_etapa = 1
        etapas_creadas = {}  # Mapeo nombre -> id de etapa en la obra

        for etapa_nombre, items_etapa in etapas_dict.items():
            # Buscar si ya existe una etapa con ese nombre en la obra
            etapa = EtapaObra.query.filter_by(obra_id=obra.id, nombre=etapa_nombre).first()

            if not etapa:
                # Verificar si hay una etapa existente (del presupuesto) que podemos asociar
                if etapa_nombre in etapas_obj_map:
                    etapa_existente = etapas_obj_map[etapa_nombre]
                    etapa_existente.obra_id = obra.id
                    etapa = etapa_existente
                    current_app.logger.info(f"Asociando etapa existente '{etapa_nombre}' (ID: {etapa.id}) a obra {obra.id}")
                else:
                    # Crear nueva etapa
                    etapa = EtapaObra(
                        obra_id=obra.id,
                        nombre=etapa_nombre,
                        orden=orden_etapa,
                        estado='pendiente',
                        progreso=0
                    )
                    db.session.add(etapa)
                    db.session.flush()  # Para obtener etapa.id
                    current_app.logger.info(f"Creada nueva etapa '{etapa_nombre}' (ID: {etapa.id}) para obra {obra.id}")

            etapas_creadas[etapa_nombre] = etapa.id

            # Actualizar etapa_id en los items si no lo tenían
            for item in items_etapa:
                if not item.etapa_id:
                    item.etapa_id = etapa.id

            # Calcular mediciones totales para esta etapa
            cantidad_total_etapa = 0
            unidad_etapa = 'm2'  # Default

            for item in items_etapa:
                if item and item.cantidad:
                    cantidad_total_etapa += float(item.cantidad)
                    if item.unidad:
                        unidad_etapa = item.unidad  # Tomar la unidad del último item

            # Asignar mediciones a la etapa
            etapa.unidad_medida = unidad_etapa
            etapa.cantidad_total_planificada = cantidad_total_etapa
            etapa.cantidad_total_ejecutada = 0
            etapa.porcentaje_avance_medicion = 0

            current_app.logger.info(f"📏 Etapa '{etapa_nombre}': {cantidad_total_etapa} {unidad_etapa} planificados")

            orden_etapa += 1

        db.session.flush()

        # Crear tareas predefinidas por etapa (tareas de OBRA, no materiales)
        if crear_tareas:
            from tareas_predefinidas import obtener_tareas_por_etapa
            tareas_creadas_count = 0

            for etapa_nombre in etapas_dict.keys():
                etapa_id = etapas_creadas[etapa_nombre]
                tareas_predefinidas = obtener_tareas_por_etapa(etapa_nombre)

                if tareas_predefinidas:
                    # Usar tareas predefinidas (son tareas de obra reales)
                    for tarea_def in tareas_predefinidas:
                        # Saltar tareas opcionales marcadas con si_aplica
                        if tarea_def.get('si_aplica'):
                            continue
                        tarea = TareaEtapa(
                            etapa_id=etapa_id,
                            nombre=tarea_def['nombre'],
                            estado='pendiente',
                            horas_estimadas=tarea_def.get('horas', 0),
                            unidad='un' if tarea_def.get('aplica_cantidad') is False else 'h',
                        )
                        db.session.add(tarea)
                        tareas_creadas_count += 1
                else:
                    # Fallback: si no hay tareas predefinidas, crear tarea genérica por etapa
                    tarea = TareaEtapa(
                        etapa_id=etapa_id,
                        nombre=f'Ejecución {etapa_nombre}',
                        estado='pendiente',
                        unidad='un',
                    )
                    db.session.add(tarea)
                    tareas_creadas_count += 1

            current_app.logger.info(f"Creadas {tareas_creadas_count} tareas predefinidas para {len(etapas_dict)} etapas en obra {obra.id}")

        db.session.commit()

        # Asignar niveles de encadenamiento, dependencias y fechas
        try:
            from services.dependency_service import (
                asignar_niveles_por_defecto,
                generar_dependencias_desde_niveles,
                propagar_fechas_obra,
            )
            from datetime import timedelta as td

            # 1. Asignar niveles de encadenamiento
            asignadas = asignar_niveles_por_defecto(obra.id)
            if asignadas:
                db.session.flush()
                current_app.logger.info(f"Niveles asignados a {asignadas} etapas de obra {obra.id}")

            # 2. Generar dependencias FS entre niveles
            deps_creadas = generar_dependencias_desde_niveles(obra.id)
            if deps_creadas:
                db.session.flush()
                current_app.logger.info(f"Creadas {deps_creadas} dependencias para obra {obra.id}")

            # 3. Asignar fecha de inicio a la primera etapa (fecha_inicio de la obra o hoy)
            from models.projects import EtapaObra as EO
            primera_etapa = EO.query.filter_by(obra_id=obra.id).order_by(
                EO.nivel_encadenamiento.asc().nullslast(), EO.orden
            ).first()
            if primera_etapa and not primera_etapa.fecha_inicio_estimada:
                fecha_inicio = obra.fecha_inicio or date.today()
                primera_etapa.fecha_inicio_estimada = fecha_inicio
                primera_etapa.fecha_fin_estimada = fecha_inicio + td(days=14)  # 2 semanas default
                db.session.flush()

            # 4. Propagar fechas a todas las etapas sucesoras
            modificadas = propagar_fechas_obra(obra.id, force_cascade=True)
            db.session.commit()
            if modificadas:
                current_app.logger.info(f"Fechas propagadas a {len(modificadas)} etapas de obra {obra.id}")

        except Exception as e_dep:
            db.session.rollback()
            current_app.logger.warning(f"Error en encadenamiento de etapas: {e_dep}")
            try:
                db.session.commit()  # Commit lo que se pueda
            except Exception:
                pass

        current_app.logger.info(f"Presupuesto {presupuesto.numero} confirmado como obra {obra.id}")

        return jsonify({
            'success': True,
            'message': f'Presupuesto confirmado exitosamente. Obra creada: {obra.nombre}',
            'obra_id': obra.id,
            'obra_url': url_for('obras.detalle', id=obra.id),
            'redirect_url': url_for('obras.detalle', id=obra.id)
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en presupuestos.confirmar_como_obra: {e}", exc_info=True)
        return jsonify({'error': 'Error al confirmar el presupuesto'}), 500


@presupuestos_bp.route('/<int:id>/editar-obra', methods=['POST'])
@login_required
def editar_obra(id):
    """Editar información de la obra/proyecto del presupuesto"""
    try:
        org_id = get_current_org_id()
        presupuesto = Presupuesto.query.filter_by(id=id, organizacion_id=org_id).first_or_404()

        # Admin, PM y técnicos pueden editar
        # Usar método centralizado de permisos
        if not current_user.puede_editar():
            return jsonify({'error': '⛔ Solo administradores, PM y técnicos pueden editar presupuestos. Contactá a tu administrador.'}), 403

        # No se puede editar si ya está confirmado como obra
        if presupuesto.confirmado_como_obra:
            return jsonify({'error': '❌ No se puede editar un presupuesto ya confirmado como obra. Si necesitás hacer cambios, contactá al administrador para revertir la confirmación.'}), 400

        data = request.get_json() or {}

        # Obtener datos del proyecto actual
        if presupuesto.datos_proyecto:
            try:
                proyecto_data = json.loads(presupuesto.datos_proyecto) if isinstance(presupuesto.datos_proyecto, str) else presupuesto.datos_proyecto
            except (json.JSONDecodeError, TypeError):
                proyecto_data = {}
        else:
            proyecto_data = {}

        # Actualizar campos del proyecto
        if 'nombre' in data:
            proyecto_data['nombre_obra'] = data['nombre'].strip()

        if 'cliente' in data:
            proyecto_data['cliente_nombre'] = data['cliente'].strip()

        if 'descripcion' in data:
            proyecto_data['descripcion'] = data['descripcion'].strip()

        if 'direccion' in data:
            proyecto_data['ubicacion'] = data['direccion'].strip()

        if 'tipo_obra' in data:
            proyecto_data['tipo_obra'] = data['tipo_obra'].strip()

        if 'superficie_m2' in data:
            superficie = data['superficie_m2']
            if superficie:
                try:
                    proyecto_data['superficie_m2'] = float(superficie)
                except (ValueError, TypeError):
                    proyecto_data['superficie_m2'] = superficie
            else:
                proyecto_data['superficie_m2'] = None

        # Actualizar cliente_id en el presupuesto si se proporciona
        if 'cliente_id' in data:
            cliente_id = data['cliente_id']
            if cliente_id:
                presupuesto.cliente_id = int(cliente_id)
            else:
                presupuesto.cliente_id = None

        # Guardar el JSON actualizado
        presupuesto.datos_proyecto = json.dumps(proyecto_data, ensure_ascii=False)

        db.session.commit()

        current_app.logger.info(f"Información del presupuesto {presupuesto.numero} actualizada")

        return jsonify({
            'exito': True,
            'mensaje': 'Información actualizada correctamente'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en presupuestos.editar_obra: {e}", exc_info=True)
        return jsonify({'error': 'Error al actualizar la información'}), 500


@presupuestos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def eliminar(id):
    """Eliminar (archivar) presupuesto"""
    try:
        # Log para debugging
        current_app.logger.info(f'Usuario {current_user.id} intentando eliminar presupuesto {id}')
        current_app.logger.info(f'Usuario rol: {getattr(current_user, "rol", None)}, role: {getattr(current_user, "role", None)}')

        # Verificar permisos usando ambos sistemas de roles
        es_admin = (getattr(current_user, 'rol', None) == 'administrador' or
                    getattr(current_user, 'role', None) == 'admin' or
                    getattr(current_user, 'is_super_admin', False))

        if not es_admin:
            current_app.logger.warning(f'Usuario {current_user.id} sin permisos de admin')
            return jsonify({'error': '⛔ Solo administradores pueden eliminar presupuestos. Contactá a tu administrador.'}), 403

        org_id = get_current_org_id()
        current_app.logger.info(f'Org ID obtenido: {org_id}')

        if not org_id:
            # Intentar obtener de usuario directamente
            org_id = getattr(current_user, 'organizacion_id', None)
            current_app.logger.info(f'Org ID de usuario: {org_id}')

        if not org_id:
            current_app.logger.warning('No se pudo obtener organización activa')
            return jsonify({'error': 'Sin organización activa'}), 400

        # Query atómica: filtrar por ID + org_id en una sola consulta (previene IDOR)
        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first()
        if not presupuesto:
            current_app.logger.warning(f'Presupuesto {id} no encontrado o sin autorización')
            return jsonify({'error': 'Presupuesto no encontrado'}), 404

        # Verificar si el presupuesto está confirmado como obra
        if presupuesto.confirmado_como_obra:
            current_app.logger.warning(f'Intento de eliminar presupuesto {id} confirmado como obra')
            return jsonify({'error': '❌ No se puede eliminar un presupuesto que ya fue confirmado como obra. Primero debés revertir la confirmación.'}), 400

        # Administradores pueden eliminar presupuestos en cualquier estado
        # (excepto confirmados como obra)
        current_app.logger.info(f'Admin eliminando presupuesto {id} en estado {presupuesto.estado}')

        # Marcar como eliminado en lugar de borrar
        presupuesto.estado = 'eliminado'
        try:
            from models.audit import registrar_audit
            registrar_audit('eliminar', 'presupuesto', id, f'Presupuesto {presupuesto.numero} eliminado')
        except Exception:
            pass
        db.session.commit()

        current_app.logger.info(f'Presupuesto {presupuesto.numero} eliminado correctamente')
        return jsonify({
            'mensaje': f'Presupuesto {presupuesto.numero} eliminado correctamente'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.eliminar: {str(e)}", exc_info=True)
        db.session.rollback()
        current_app.logger.error(f'Error al eliminar presupuesto: {e}'); return jsonify({'error': 'Error al eliminar el presupuesto'}), 500


@presupuestos_bp.route('/<int:id>/cambiar-estado', methods=['POST'])
@login_required
def cambiar_estado(id):
    """Cambiar estado del presupuesto"""
    if not current_user.puede_gestionar():
        flash('No tienes permisos para cambiar el estado', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))

    try:
        org_id = get_current_org_id()
        if not org_id:
            flash('No tienes una organización activa', 'warning')
            return redirect(url_for('index'))

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        nuevo_estado = request.form.get('estado', '').strip()
        estados_validos = ['borrador', 'enviado', 'aprobado', 'confirmado', 'rechazado', 'perdido', 'vencido']

        if nuevo_estado not in estados_validos:
            flash('Estado inválido', 'danger')
            return redirect(url_for('presupuestos.detalle', id=id))

        presupuesto.estado = nuevo_estado
        db.session.commit()

        flash(f'Estado cambiado a {nuevo_estado}', 'success')
        return redirect(url_for('presupuestos.detalle', id=id))

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.cambiar_estado: {e}")
        db.session.rollback()
        flash('Error al cambiar el estado', 'danger')
        return redirect(url_for('presupuestos.detalle', id=id))


@presupuestos_bp.route('/<int:id>/revertir-borrador', methods=['POST'])
@login_required
def revertir_borrador(id):
    """Revertir presupuesto a estado borrador (solo administradores)"""
    try:
        # Solo administradores
        if not current_user.es_admin():
            return jsonify({'error': 'Solo administradores pueden revertir presupuestos'}), 403

        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Verificar que el presupuesto esté en un estado que permita revertir
        if presupuesto.estado not in ['enviado', 'aprobado', 'rechazado', 'perdido']:
            return jsonify({'error': f'No se puede revertir un presupuesto en estado {presupuesto.estado}'}), 400

        # Revertir a borrador
        estado_anterior = presupuesto.estado
        presupuesto.estado = 'borrador'

        # Si estaba marcado como perdido, limpiar esos datos
        if estado_anterior == 'perdido':
            presupuesto.perdido_motivo = None
            presupuesto.perdido_fecha = None

        db.session.commit()

        return jsonify({
            'mensaje': f'Presupuesto {presupuesto.numero} revertido a borrador exitosamente',
            'estado_anterior': estado_anterior,
            'estado_nuevo': 'borrador'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.revertir_borrador: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': 'Error al revertir el presupuesto'}), 500


@presupuestos_bp.route('/<int:id>/restaurar', methods=['POST'])
@login_required
def restaurar(id):
    """Restaurar presupuesto perdido a borrador"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Solo se pueden restaurar presupuestos perdidos
        if presupuesto.estado != 'perdido':
            return jsonify({'error': 'Solo se pueden restaurar presupuestos marcados como perdidos'}), 400

        presupuesto.estado = 'borrador'
        presupuesto.perdido_motivo = None
        presupuesto.perdido_fecha = None
        db.session.commit()

        return jsonify({
            'mensaje': f'Presupuesto {presupuesto.numero} restaurado a borrador'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.restaurar: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': 'Error al restaurar el presupuesto'}), 500


@presupuestos_bp.route('/<int:id>/asignar-cliente', methods=['POST'])
@login_required
def asignar_cliente(id):
    """Asignar un cliente existente al presupuesto"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'exito': False, 'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        data = request.get_json()
        cliente_id = data.get('cliente_id')

        if not cliente_id:
            return jsonify({'exito': False, 'error': 'Debe seleccionar un cliente'}), 400

        # Convertir a entero
        try:
            cliente_id = int(cliente_id)
        except (ValueError, TypeError):
            return jsonify({'exito': False, 'error': 'ID de cliente inválido'}), 400

        # Verificar que el cliente existe y pertenece a la organización
        cliente = Cliente.query.filter_by(
            id=cliente_id,
            organizacion_id=org_id
        ).first()

        if not cliente:
            return jsonify({'exito': False, 'error': 'Cliente no encontrado'}), 404

        # Asignar cliente
        presupuesto.cliente_id = cliente.id
        db.session.commit()

        return jsonify({
            'exito': True,
            'mensaje': f'Cliente {cliente.nombre_completo} asignado correctamente',
            'cliente_id': cliente.id,
            'cliente_nombre': cliente.nombre_completo
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.asignar_cliente: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'exito': False, 'error': 'Error al asignar cliente'}), 500


@presupuestos_bp.route('/<int:id>/crear-asignar-cliente', methods=['POST'])
@login_required
def crear_asignar_cliente(id):
    """Crear un cliente nuevo y asignarlo al presupuesto"""
    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'exito': False, 'error': 'Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        data = request.get_json()
        nombre = data.get('nombre', '').strip()
        apellido = data.get('apellido', '').strip() or ''
        email = data.get('email', '').strip()
        telefono = data.get('telefono', '').strip()
        tipo_documento = data.get('tipo_documento', 'CUIT').strip()
        numero_documento = data.get('numero_documento', '').strip()

        # Validaciones
        if not nombre:
            return jsonify({'exito': False, 'error': 'El nombre es requerido'}), 400
        if not email:
            return jsonify({'exito': False, 'error': 'El email es requerido'}), 400
        if not numero_documento:
            return jsonify({'exito': False, 'error': 'El número de documento es requerido'}), 400

        # Verificar si ya existe un cliente con ese documento
        existing = Cliente.query.filter_by(
            organizacion_id=org_id,
            numero_documento=numero_documento
        ).first()

        if existing:
            return jsonify({
                'exito': False,
                'error': f'Ya existe un cliente con el documento {numero_documento}'
            }), 400

        # Crear cliente
        cliente = Cliente(
            organizacion_id=org_id,
            nombre=nombre,
            apellido=apellido,
            tipo_documento=tipo_documento,
            numero_documento=numero_documento,
            email=email,
            telefono=telefono or None,
            empresa=nombre if not apellido else None  # Si no hay apellido, usar nombre como empresa
        )

        db.session.add(cliente)
        db.session.flush()  # Para obtener el ID

        # Asignar al presupuesto
        presupuesto.cliente_id = cliente.id
        db.session.commit()

        return jsonify({
            'exito': True,
            'mensaje': f'Cliente {cliente.nombre_completo} creado y asignado correctamente',
            'cliente_id': cliente.id,
            'cliente_nombre': cliente.nombre_completo
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.crear_asignar_cliente: {e}", exc_info=True)
        db.session.rollback()
        current_app.logger.error(f'Error al crear cliente: {e}'); return jsonify({'exito': False, 'error': 'Error al crear cliente'}), 500


@presupuestos_bp.route('/<int:id>/revertir-confirmacion', methods=['POST'])
@login_required
def revertir_confirmacion_obra(id):
    """Revertir confirmación de obra - SOLO ADMINISTRADORES

    Esta función permite a los administradores deshacer la confirmación de un
    presupuesto como obra. ATENCIÓN: Esto puede causar inconsistencias si la
    obra ya tiene avances registrados.
    """
    try:
        # Solo administradores pueden revertir confirmaciones
        if not current_user.es_admin():
            return jsonify({
                'error': '⛔ Solo administradores pueden revertir confirmaciones de obra. Esta operación requiere privilegios especiales.'
            }), 403

        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'error': '❌ Sin organización activa'}), 400

        presupuesto = Presupuesto.query.filter_by(
            id=id,
            organizacion_id=org_id
        ).first_or_404()

        # Verificar que el presupuesto esté confirmado como obra
        if not presupuesto.confirmado_como_obra:
            return jsonify({
                'error': '❌ Este presupuesto no está confirmado como obra. No hay nada que revertir.'
            }), 400

        # Obtener la obra asociada
        from models import Obra, TareaEtapa, TareaAvance, Etapa
        obra = None
        if presupuesto.obra_id:
            obra = Obra.query.get(presupuesto.obra_id)

        # Verificar si hay avances registrados en la obra (esto es una operación delicada)
        tiene_avances = False
        mensaje_advertencia = ""

        if obra:
            # Contar avances en todas las tareas de la obra
            avances_count = db.session.query(TareaAvance).join(TareaEtapa).filter(
                TareaEtapa.etapa_id.in_(
                    db.session.query(Etapa.id).filter(Etapa.obra_id == obra.id)
                )
            ).count()

            tiene_avances = avances_count > 0

            if tiene_avances:
                mensaje_advertencia = f"⚠️ ADVERTENCIA: La obra tiene {avances_count} avance(s) registrado(s). "

        # Revertir la confirmación
        presupuesto.confirmado_como_obra = False
        presupuesto.obra_id = None
        presupuesto.estado = 'borrador'  # Volver a borrador para permitir edición

        # NO eliminamos la obra porque puede tener datos importantes
        # El administrador debe manejar eso manualmente si es necesario

        db.session.commit()

        current_app.logger.info(
            f"Admin {current_user.id} revirtió confirmación de obra para presupuesto {presupuesto.numero}"
        )

        return jsonify({
            'exito': True,
            'mensaje': f'{mensaje_advertencia}Confirmación revertida exitosamente. El presupuesto {presupuesto.numero} volvió a estado borrador.',
            'presupuesto_numero': presupuesto.numero,
            'tenia_avances': tiene_avances,
            'obra_id': obra.id if obra else None
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.revertir_confirmacion_obra: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'error': 'Error al revertir la confirmación'
        }), 500


@presupuestos_bp.route('/guardar', methods=['POST'])
@login_required
def guardar_presupuesto():
    """Guardar presupuesto desde calculadora IA"""
    if not current_user.puede_gestionar():
        return jsonify({'ok': False, 'error': 'No tienes permisos'}), 403

    try:
        org_id = get_current_org_id()
        if not org_id:
            return jsonify({'ok': False, 'error': 'Sin organización activa'}), 400

        data = request.get_json() or request.form.to_dict()

        # Crear presupuesto
        numero = data.get('numero', f"PRES-{date.today().strftime('%Y%m%d')}")

        presupuesto = Presupuesto(
            organizacion_id=org_id,
            numero=numero,
            obra_id=data.get('obra_id'),
            cliente_nombre=data.get('cliente_nombre', ''),
            fecha=date.today(),
            vigencia_dias=30,
            estado='borrador',
            currency='ARS',
            iva_porcentaje=BudgetConstants.DEFAULT_IVA_RATE
        )

        db.session.add(presupuesto)
        db.session.flush()

        # Agregar items si vienen en el payload
        items_data = data.get('items', [])
        for item_data in items_data:
            item = ItemPresupuesto(
                presupuesto_id=presupuesto.id,
                descripcion=item_data.get('descripcion', ''),
                tipo=item_data.get('tipo', 'material'),
                cantidad=Decimal(str(item_data.get('cantidad', 0))),
                unidad=item_data.get('unidad', 'un'),
                precio_unitario=Decimal(str(item_data.get('precio_unitario', 0))),
                subtotal=Decimal(str(item_data.get('subtotal', 0))),
                orden=item_data.get('orden', 0)
            )
            db.session.add(item)

        db.session.commit()

        return jsonify({
            'ok': True,
            'presupuesto_id': presupuesto.id,
            'message': 'Presupuesto guardado exitosamente'
        })

    except Exception as e:
        current_app.logger.error(f"Error en presupuestos.guardar_presupuesto: {e}")
        db.session.rollback()
        current_app.logger.error(f'Error presupuestos: {e}'); return jsonify({'ok': False, 'error': 'Error interno del servidor'}), 500
