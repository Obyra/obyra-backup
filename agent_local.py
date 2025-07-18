from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import current_user, login_required
from models import Obra, Presupuesto, ItemInventario, Usuario, db
from sqlalchemy import func
from datetime import datetime, timedelta

agent_bp = Blueprint('agent_local', __name__)


@agent_bp.route('/diagnostico-agent')
@login_required
def diagnostico_agent():
    if not current_user.rol == 'administrador':
        return redirect(url_for('reportes.dashboard'))  # Redirige si no es admin

    return render_template('asistente/diagnostico_agent.html', user=current_user)


@agent_bp.route('/api/agente-consulta', methods=['POST'])
@login_required
def procesar_consulta():
    """Procesa consultas del agente IA con datos reales de la organización"""
    try:
        data = request.get_json()
        consulta = data.get('consulta', '').lower()
        
        # Obtener datos reales de la organización del usuario
        org_id = current_user.organizacion_id
        
        # Consultar obras activas
        obras_activas = Obra.query.filter_by(
            organizacion_id=org_id,
            estado='en_progreso'
        ).all()
        
        obras_total = Obra.query.filter_by(organizacion_id=org_id).count()
        
        # Consultar presupuestos
        presupuestos_aprobados = Presupuesto.query.filter_by(
            organizacion_id=org_id,
            estado='aprobado'
        ).all()
        
        # Consultar inventario con stock bajo
        items_stock_bajo = ItemInventario.query.filter(
            ItemInventario.organizacion_id == org_id,
            ItemInventario.stock_actual <= ItemInventario.stock_minimo
        ).all()
        
        # Generar respuesta basada en la consulta
        if 'obra' in consulta or 'construcción' in consulta or 'proyecto' in consulta:
            if not obras_activas:
                if obras_total == 0:
                    respuesta = "Actualmente no tienes obras registradas en el sistema. Te recomiendo crear tu primera obra desde el menú 'Obras' → 'Nueva Obra'."
                else:
                    obras_otras = Obra.query.filter_by(organizacion_id=org_id).all()
                    estados = [obra.estado for obra in obras_otras]
                    respuesta = f"No tienes obras activas en este momento. Tienes {obras_total} obra(s) registrada(s) con los siguientes estados: {', '.join(set(estados))}."
            else:
                respuesta = f"Tienes <strong>{len(obras_activas)} obra(s) activa(s)</strong> en construcción:<br><br>"
                for obra in obras_activas:
                    progreso = obra.progreso or 0
                    respuesta += f"• <strong>{obra.nombre}</strong> - {progreso}% de progreso<br>"
                    respuesta += f"  Cliente: {obra.cliente}<br>"
                    if obra.fecha_fin_estimada:
                        respuesta += f"  Fecha estimada de finalización: {obra.fecha_fin_estimada.strftime('%d/%m/%Y')}<br>"
                    respuesta += "<br>"
                
                respuesta += "¿Te gustaría ver detalles específicos de alguna obra?"
        
        elif 'presupuesto' in consulta or 'costo' in consulta or 'precio' in consulta:
            if not presupuestos_aprobados:
                respuesta = "No tienes presupuestos aprobados en este momento. Puedes crear y gestionar presupuestos desde el menú 'Presupuestos'."
            else:
                total_valor = sum(p.total_con_iva or 0 for p in presupuestos_aprobados)
                respuesta = f"Tienes <strong>{len(presupuestos_aprobados)} presupuesto(s) aprobado(s)</strong> por un valor total de <strong>${total_valor:,.2f}</strong>:<br><br>"
                for presupuesto in presupuestos_aprobados:
                    respuesta += f"• <strong>{presupuesto.numero}</strong> - ${presupuesto.total_con_iva:,.2f}<br>"
                    if presupuesto.obra:
                        respuesta += f"  Obra: {presupuesto.obra.nombre}<br>"
                    respuesta += "<br>"
        
        elif 'inventario' in consulta or 'stock' in consulta or 'material' in consulta:
            if items_stock_bajo:
                respuesta = f"⚠️ <strong>Alerta de inventario:</strong> Tienes {len(items_stock_bajo)} elemento(s) con stock bajo:<br><br>"
                for item in items_stock_bajo:
                    respuesta += f"• <strong>{item.nombre}</strong><br>"
                    respuesta += f"  Stock actual: {item.stock_actual} {item.unidad}<br>"
                    respuesta += f"  Stock mínimo: {item.stock_minimo} {item.unidad}<br><br>"
                respuesta += "Te recomiendo reabastecer estos elementos pronto."
            else:
                total_items = ItemInventario.query.filter_by(organizacion_id=org_id).count()
                if total_items == 0:
                    respuesta = "No tienes elementos en el inventario. Puedes agregar materiales, herramientas y equipos desde el menú 'Inventario'."
                else:
                    respuesta = f"Tu inventario está en buen estado. Tienes {total_items} elemento(s) registrado(s) y todos tienen stock suficiente."
        
        elif 'usuario' in consulta or 'equipo' in consulta or 'persona' in consulta:
            usuarios_activos = Usuario.query.filter_by(
                organizacion_id=org_id,
                activo=True
            ).count()
            respuesta = f"Tu organización tiene <strong>{usuarios_activos} usuario(s) activo(s)</strong>. Puedes gestionar el equipo desde el menú 'Equipos'."
        
        else:
            # Respuesta general con resumen
            respuesta = f"""<strong>Resumen de tu organización:</strong><br><br>
            • <strong>Obras activas:</strong> {len(obras_activas)}<br>
            • <strong>Obras totales:</strong> {obras_total}<br>
            • <strong>Presupuestos aprobados:</strong> {len(presupuestos_aprobados)}<br>
            • <strong>Elementos con stock bajo:</strong> {len(items_stock_bajo)}<br><br>
            Puedes hacer preguntas específicas sobre obras, presupuestos, inventario o usuarios."""
        
        return jsonify({
            'respuesta': respuesta,
            'tiempo_respuesta': 150,  # Simulado
            'datos_reales': True
        })
    
    except Exception as e:
        return jsonify({
            'respuesta': f'Error al procesar la consulta: {str(e)}',
            'tiempo_respuesta': 0,
            'datos_reales': False
        }), 500
