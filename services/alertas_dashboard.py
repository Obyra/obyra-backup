"""
Servicio de alertas para el dashboard.
Genera alertas reales basadas en:
- Stock bajo de materiales
- Presupuestos por vencer
- Obras demoradas
- Tareas no completadas pasada la fecha
- Sobrecosto de obra
"""
from datetime import date, datetime, timedelta, timezone

# Timezone Argentina (UTC-3)
_AR_TZ = timezone(timedelta(hours=-3))


def _hoy_argentina():
    return datetime.now(_AR_TZ).replace(tzinfo=None).date()
from decimal import Decimal
from sqlalchemy import and_, or_
from extensions import db


def obtener_alertas_stock_bajo(org_id, limite=5):
    """
    Obtiene items de inventario con stock bajo o sin stock.

    Solo considera items con stock_minimo > 0 (configuración explícita
    de nivel crítico). Items recién auto-creados desde OC tienen
    stock_minimo=0 por default y no son stock crítico hasta que el
    usuario configure un umbral.

    Cruza con OCs pendientes: si el item tiene una OC emitida o de
    recepción parcial sin completar, la severidad baja a 'media' con
    texto "en tránsito", porque el material está en camino.
    """
    from models import ItemInventario
    from models.inventory import OrdenCompra, OrdenCompraItem

    items = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.activo == True,
        ItemInventario.stock_minimo > 0,
        ItemInventario.stock_actual <= ItemInventario.stock_minimo
    ).order_by(ItemInventario.stock_actual).limit(limite).all()

    # Items con OC pendiente de recepción (subquery para evitar N+1).
    # Se considera "pendiente" si hay OrdenCompraItem en OC con estado
    # 'emitida' o 'recibida_parcial', y cantidad_recibida < cantidad.
    item_ids = [i.id for i in items]
    items_con_oc_pendiente = {}
    if item_ids:
        pendientes = db.session.query(
            OrdenCompraItem.item_inventario_id,
            OrdenCompra.numero,
            OrdenCompra.fecha_entrega_estimada,
        ).join(
            OrdenCompra, OrdenCompraItem.orden_compra_id == OrdenCompra.id
        ).filter(
            OrdenCompraItem.item_inventario_id.in_(item_ids),
            OrdenCompra.estado.in_(['emitida', 'recibida_parcial']),
            OrdenCompraItem.cantidad > OrdenCompraItem.cantidad_recibida,
        ).all()
        for item_id, oc_num, fecha in pendientes:
            # Quedarse con la entrega más próxima por si hay varias OCs
            existing = items_con_oc_pendiente.get(item_id)
            if not existing or (fecha and existing[1] and fecha < existing[1]):
                items_con_oc_pendiente[item_id] = (oc_num, fecha)

    alertas = []
    for item in items:
        oc_pendiente = items_con_oc_pendiente.get(item.id)

        if oc_pendiente:
            # Hay OC llegando — baja severidad, etiqueta "en tránsito"
            oc_num, fecha = oc_pendiente
            severidad = 'media'
            titulo = f'Stock bajo (en tránsito): {item.nombre}'
            fecha_txt = f', llega {fecha.strftime("%d/%m")}' if fecha else ''
            descripcion = (f'{item.stock_actual:.0f} {item.unidad} disponibles '
                           f'(min: {item.stock_minimo:.0f}) — OC {oc_num} pendiente{fecha_txt}')
        elif item.stock_actual <= 0:
            severidad = 'critica'
            titulo = f'Sin stock: {item.nombre}'
            descripcion = f'{item.stock_actual:.0f} {item.unidad} disponibles (min: {item.stock_minimo:.0f})'
        elif item.stock_actual <= (item.stock_minimo * Decimal('0.25')):
            severidad = 'alta'
            titulo = f'Stock critico: {item.nombre}'
            descripcion = f'{item.stock_actual:.0f} {item.unidad} disponibles (min: {item.stock_minimo:.0f})'
        else:
            severidad = 'media'
            titulo = f'Stock bajo: {item.nombre}'
            descripcion = f'{item.stock_actual:.0f} {item.unidad} disponibles (min: {item.stock_minimo:.0f})'

        alertas.append({
            'tipo': 'stock_bajo',
            'severidad': severidad,
            'titulo': titulo,
            'descripcion': descripcion,
            'referencia': item.codigo or item.nombre,
            'url': f'/inventario/item/{item.id}',
            'item': item
        })

    return alertas


def obtener_alertas_presupuestos_vencer(org_id, limite=5):
    """
    Obtiene presupuestos que estan por vencer o ya vencieron.
    """
    from models import Presupuesto

    hoy = date.today()
    fecha_limite = hoy + timedelta(days=15)

    presupuestos = Presupuesto.query.filter(
        Presupuesto.organizacion_id == org_id,
        Presupuesto.deleted_at.is_(None),
        Presupuesto.fecha_vigencia.isnot(None),
        Presupuesto.fecha_vigencia <= fecha_limite,
        Presupuesto.estado.in_(['borrador', 'enviado']),
        Presupuesto.confirmado_como_obra == False
    ).order_by(Presupuesto.fecha_vigencia).limit(limite).all()

    alertas = []
    for pres in presupuestos:
        dias = (pres.fecha_vigencia - hoy).days

        if dias < 0:
            severidad = 'critica'
            titulo = f'Presupuesto vencido: {pres.numero}'
            desc = f'Vencio hace {abs(dias)} dia(s)'
        elif dias <= 3:
            severidad = 'critica'
            titulo = f'Presupuesto por vencer: {pres.numero}'
            desc = f'Vence en {dias} dia(s)'
        elif dias <= 7:
            severidad = 'alta'
            titulo = f'Presupuesto por vencer: {pres.numero}'
            desc = f'Vence en {dias} dias'
        else:
            severidad = 'media'
            titulo = f'Presupuesto proximo a vencer: {pres.numero}'
            desc = f'Vence en {dias} dias'

        alertas.append({
            'tipo': 'presupuesto_vencer',
            'severidad': severidad,
            'titulo': titulo,
            'descripcion': desc,
            'referencia': pres.cliente_nombre or 'Sin cliente',
            'url': f'/presupuestos/{pres.id}',
            'presupuesto': pres
        })

    return alertas


def obtener_alertas_obras_demoradas(org_id, limite=5):
    """
    Obtiene obras que estan demoradas (fecha fin estimada ya paso).
    """
    from models import Obra

    hoy = date.today()

    obras = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.deleted_at.is_(None),
        Obra.estado.in_(['planificacion', 'en_curso']),
        Obra.fecha_fin_estimada.isnot(None),
        Obra.fecha_fin_estimada < hoy
    ).order_by(Obra.fecha_fin_estimada).limit(limite).all()

    alertas = []
    for obra in obras:
        dias_demora = (hoy - obra.fecha_fin_estimada).days

        if dias_demora > 30:
            severidad = 'critica'
        elif dias_demora > 14:
            severidad = 'alta'
        else:
            severidad = 'media'

        alertas.append({
            'tipo': 'obra_demorada',
            'severidad': severidad,
            'titulo': f'Obra demorada: {obra.nombre[:30]}',
            'descripcion': f'{dias_demora} dias de demora - Progreso: {obra.progreso}%',
            'referencia': obra.cliente or 'Sin cliente',
            'url': f'/obras/{obra.id}',
            'obra': obra
        })

    return alertas


def obtener_alertas_tareas_vencidas(org_id, limite=5):
    """
    Obtiene tareas que no fueron completadas pasada su fecha de finalizacion.
    """
    from models import TareaEtapa, EtapaObra, Obra

    hoy = date.today()

    tareas = db.session.query(TareaEtapa).join(
        EtapaObra, TareaEtapa.etapa_id == EtapaObra.id
    ).join(
        Obra, EtapaObra.obra_id == Obra.id
    ).filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso']),
        TareaEtapa.estado.in_(['pendiente', 'en_curso']),
        or_(
            and_(TareaEtapa.fecha_fin_estimada.isnot(None), TareaEtapa.fecha_fin_estimada < hoy),
            and_(TareaEtapa.fecha_fin_plan.isnot(None), TareaEtapa.fecha_fin_plan < hoy),
            and_(TareaEtapa.fecha_fin.isnot(None), TareaEtapa.fecha_fin < hoy)
        )
    ).order_by(TareaEtapa.fecha_fin_estimada).limit(limite).all()

    alertas = []
    for tarea in tareas:
        # Determinar fecha de vencimiento
        fecha_venc = tarea.fecha_fin_estimada or tarea.fecha_fin_plan or tarea.fecha_fin
        if fecha_venc:
            dias_demora = (hoy - fecha_venc).days
        else:
            dias_demora = 0

        if dias_demora > 14:
            severidad = 'critica'
        elif dias_demora > 7:
            severidad = 'alta'
        else:
            severidad = 'media'

        obra_nombre = tarea.etapa.obra.nombre if tarea.etapa and tarea.etapa.obra else 'Sin obra'

        alertas.append({
            'tipo': 'tarea_vencida',
            'severidad': severidad,
            'titulo': f'Tarea sin completar: {tarea.nombre[:25]}',
            'descripcion': f'{dias_demora} dias de demora - Avance: {tarea.porcentaje_avance or 0}%',
            'referencia': obra_nombre[:30],
            'url': f'/obras/{tarea.etapa.obra_id}' if tarea.etapa else '#',
            'tarea': tarea
        })

    return alertas


def obtener_alertas_tareas_en_riesgo(org_id, limite=5):
    """
    Obtiene tareas que estan en riesgo de no completarse a tiempo.
    Criterios: fecha de fin dentro de los proximos 7 dias y avance insuficiente.
    NO incluye tareas ya vencidas (eso lo cubre obtener_alertas_tareas_vencidas).
    """
    from models import TareaEtapa, EtapaObra, Obra

    hoy = date.today()
    en_7_dias = hoy + timedelta(days=7)

    tareas = db.session.query(TareaEtapa).join(
        EtapaObra, TareaEtapa.etapa_id == EtapaObra.id
    ).join(
        Obra, EtapaObra.obra_id == Obra.id
    ).filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso']),
        TareaEtapa.estado.in_(['pendiente', 'en_curso']),
        or_(
            and_(TareaEtapa.fecha_fin_plan.isnot(None),
                 TareaEtapa.fecha_fin_plan >= hoy,
                 TareaEtapa.fecha_fin_plan <= en_7_dias),
            and_(TareaEtapa.fecha_fin_estimada.isnot(None),
                 TareaEtapa.fecha_fin_estimada >= hoy,
                 TareaEtapa.fecha_fin_estimada <= en_7_dias),
            and_(TareaEtapa.fecha_fin.isnot(None),
                 TareaEtapa.fecha_fin >= hoy,
                 TareaEtapa.fecha_fin <= en_7_dias)
        )
    ).all()

    alertas = []
    for tarea in tareas:
        avance = float(tarea.porcentaje_avance or 0)
        fecha_venc = tarea.fecha_fin_plan or tarea.fecha_fin_estimada or tarea.fecha_fin
        if not fecha_venc:
            continue

        dias_restantes = (fecha_venc - hoy).days

        if dias_restantes <= 3 and avance < 50:
            severidad = 'alta'
        elif dias_restantes <= 7 and avance < 70:
            severidad = 'media'
        else:
            continue

        obra_nombre = tarea.etapa.obra.nombre if tarea.etapa and tarea.etapa.obra else 'Sin obra'

        alertas.append({
            'tipo': 'tarea_en_riesgo',
            'severidad': severidad,
            'titulo': f'En riesgo: {tarea.nombre[:30]}',
            'descripcion': f'{dias_restantes} dia(s) restantes - Avance: {avance:.0f}%',
            'referencia': obra_nombre[:30],
            'url': f'/obras/{tarea.etapa.obra_id}' if tarea.etapa else '#',
        })

    orden_severidad = {'alta': 0, 'media': 1}
    alertas.sort(key=lambda x: orden_severidad.get(x['severidad'], 2))
    return alertas[:limite]


def obtener_alertas_etapas_demoradas(org_id, limite=5):
    """
    Obtiene etapas de obra que estan demoradas (fecha fin estimada ya paso
    y la etapa sigue pendiente o en_curso).
    """
    from models import EtapaObra, Obra

    hoy = date.today()

    etapas = db.session.query(EtapaObra).join(
        Obra, EtapaObra.obra_id == Obra.id
    ).filter(
        Obra.organizacion_id == org_id,
        Obra.estado.in_(['planificacion', 'en_curso']),
        EtapaObra.estado.in_(['pendiente', 'en_curso']),
        EtapaObra.fecha_fin_estimada.isnot(None),
        EtapaObra.fecha_fin_estimada < hoy
    ).order_by(EtapaObra.fecha_fin_estimada).limit(limite).all()

    alertas = []
    for etapa in etapas:
        dias_demora = (hoy - etapa.fecha_fin_estimada).days
        progreso = etapa.progreso if hasattr(etapa, 'progreso') and etapa.progreso else 0

        if dias_demora > 14:
            severidad = 'critica'
        elif dias_demora > 7:
            severidad = 'alta'
        else:
            severidad = 'media'

        obra_nombre = etapa.obra.nombre if etapa.obra else 'Sin obra'

        alertas.append({
            'tipo': 'etapa_demorada',
            'severidad': severidad,
            'titulo': f'Etapa demorada: {etapa.nombre[:30]}',
            'descripcion': f'{dias_demora} dia(s) de demora - Avance: {progreso}% - {obra_nombre[:25]}',
            'referencia': obra_nombre[:30],
            'url': f'/obras/{etapa.obra_id}',
            'etapa': etapa
        })

    return alertas


def obtener_alertas_sobrecosto(org_id, limite=5, umbral_porcentaje=10):
    """
    Obtiene obras con sobrecosto respecto al presupuesto.
    """
    from models import Obra

    obras = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.deleted_at.is_(None),
        Obra.estado.in_(['en_curso']),
        Obra.presupuesto_total > 0,
        Obra.costo_real > 0
    ).all()

    alertas = []
    for obra in obras:
        if obra.presupuesto_total and obra.presupuesto_total > 0:
            presupuesto = Decimal(str(obra.presupuesto_total))
            costo = Decimal(str(obra.costo_real or 0))

            if costo > presupuesto:
                exceso = costo - presupuesto
                porcentaje_exceso = float((exceso / presupuesto) * 100)

                if porcentaje_exceso >= umbral_porcentaje:
                    if porcentaje_exceso > 25:
                        severidad = 'critica'
                    elif porcentaje_exceso > 15:
                        severidad = 'alta'
                    else:
                        severidad = 'media'

                    alertas.append({
                        'tipo': 'sobrecosto',
                        'severidad': severidad,
                        'titulo': f'Sobrecosto: {obra.nombre[:30]}',
                        'descripcion': f'Costo supera presupuesto en {porcentaje_exceso:.1f}%',
                        'referencia': f'${exceso:,.0f} de exceso',
                        'url': f'/obras/{obra.id}',
                        'obra': obra
                    })

    # Ordenar por severidad y limitar
    orden_severidad = {'critica': 0, 'alta': 1, 'media': 2}
    alertas.sort(key=lambda x: orden_severidad.get(x['severidad'], 3))

    return alertas[:limite]


def obtener_alertas_fichadas(org_id, limite=5):
    """
    Detecta operarios con tareas activas que no ficharon ingreso (después de 5am)
    o no ficharon egreso (después de 17hs). Solo lunes a viernes.
    También envía notificaciones a los operarios afectados.
    """
    from models import Obra, Fichada, Usuario
    from models.projects import TareaEtapa, TareaMiembro, EtapaObra

    hoy = _hoy_argentina()
    ahora = datetime.now(_AR_TZ).replace(tzinfo=None)
    hora_actual = ahora.hour

    # Solo alertar lunes a viernes
    if hoy.weekday() >= 5:
        return []

    alertas = []

    try:
        # Buscar operarios con tareas activas HOY
        # (tareas en_curso o pendiente, cuya fecha incluye hoy)
        operarios_con_tareas = db.session.query(
            TareaMiembro.user_id,
            TareaEtapa.id.label('tarea_id'),
            TareaEtapa.nombre.label('tarea_nombre'),
            EtapaObra.obra_id
        ).join(
            TareaEtapa, TareaMiembro.tarea_id == TareaEtapa.id
        ).join(
            EtapaObra, TareaEtapa.etapa_id == EtapaObra.id
        ).join(
            Obra, EtapaObra.obra_id == Obra.id
        ).filter(
            Obra.organizacion_id == org_id,
            Obra.estado == 'en_curso',
            TareaEtapa.estado.in_(['pendiente', 'en_curso']),
            db.or_(
                # Tarea con fechas estimadas que incluyen hoy
                db.and_(
                    TareaEtapa.fecha_inicio_estimada <= hoy,
                    TareaEtapa.fecha_fin_estimada >= hoy
                ),
                # O tarea en_curso sin fechas específicas
                db.and_(
                    TareaEtapa.estado == 'en_curso',
                    TareaEtapa.fecha_inicio_estimada.is_(None)
                )
            )
        ).all()

        if not operarios_con_tareas:
            return []

        # Agrupar por operario: {user_id: {obra_ids, tareas}}
        operarios_info = {}
        for row in operarios_con_tareas:
            if row.user_id not in operarios_info:
                operarios_info[row.user_id] = {'obra_ids': set(), 'tareas': []}
            operarios_info[row.user_id]['obra_ids'].add(row.obra_id)
            operarios_info[row.user_id]['tareas'].append(row.tarea_nombre)

        user_ids = list(operarios_info.keys())

        # Buscar fichadas de hoy para estos operarios
        fichadas_hoy = Fichada.query.filter(
            Fichada.usuario_id.in_(user_ids),
            db.func.date(Fichada.fecha_hora) == hoy
        ).all()

        # Mapear: {user_id: {'ingreso': bool, 'egreso': bool}}
        fichadas_map = {}
        for f in fichadas_hoy:
            if f.usuario_id not in fichadas_map:
                fichadas_map[f.usuario_id] = {'ingreso': False, 'egreso': False}
            if f.tipo == 'ingreso':
                fichadas_map[f.usuario_id]['ingreso'] = True
            elif f.tipo == 'egreso':
                fichadas_map[f.usuario_id]['egreso'] = True

        # Después de las 5am: alertar sin ingreso
        sin_ingreso = []
        sin_egreso = []

        if hora_actual >= 5:
            for uid in user_ids:
                estado = fichadas_map.get(uid, {'ingreso': False, 'egreso': False})
                if not estado['ingreso']:
                    sin_ingreso.append(uid)

        # Después de las 17hs: alertar sin egreso (solo si fichó ingreso)
        if hora_actual >= 17:
            for uid in user_ids:
                estado = fichadas_map.get(uid, {'ingreso': False, 'egreso': False})
                if estado['ingreso'] and not estado['egreso']:
                    sin_egreso.append(uid)

        # Generar alertas de ingreso
        if sin_ingreso:
            usuarios = Usuario.query.filter(
                Usuario.id.in_(sin_ingreso), Usuario.activo == True
            ).all()

            for u in usuarios:
                tareas = operarios_info[u.id]['tareas'][:2]
                tareas_str = ', '.join(tareas)
                if len(operarios_info[u.id]['tareas']) > 2:
                    tareas_str += f' (+{len(operarios_info[u.id]["tareas"]) - 2})'

                alertas.append({
                    'tipo': 'sin_fichada_ingreso',
                    'severidad': 'alta' if hora_actual >= 9 else 'media',
                    'titulo': f'{u.nombre_completo} no fichó ingreso',
                    'descripcion': f'Tareas activas: {tareas_str}',
                    'referencia': f'Desde las 5:00 hs - Ahora {hora_actual}:{ahora.minute:02d} hs',
                    'url': '/fichadas/historial',
                })

                # Enviar notificación al operario
                _notificar_fichada_pendiente(u.id, org_id, 'ingreso', tareas_str)

        # Generar alertas de egreso
        if sin_egreso:
            usuarios = Usuario.query.filter(
                Usuario.id.in_(sin_egreso), Usuario.activo == True
            ).all()

            for u in usuarios:
                alertas.append({
                    'tipo': 'sin_fichada_egreso',
                    'severidad': 'media',
                    'titulo': f'{u.nombre_completo} no fichó egreso',
                    'descripcion': 'Fichó ingreso pero no registró salida',
                    'referencia': f'Hora mínima salida: 17:00 hs',
                    'url': '/fichadas/historial',
                })

                # Enviar notificación al operario
                _notificar_fichada_pendiente(u.id, org_id, 'egreso', '')

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error alertas fichadas: {e}")

    return alertas[:limite]


def _notificar_fichada_pendiente(usuario_id, org_id, tipo_fichada, tareas_str):
    """Envía notificación al operario si no tiene una igual hoy."""
    try:
        from models.core import Notificacion

        hoy = _hoy_argentina()

        # No duplicar: verificar si ya se envió hoy
        ya_existe = Notificacion.query.filter(
            Notificacion.usuario_id == usuario_id,
            Notificacion.tipo == f'fichada_{tipo_fichada}_pendiente',
            db.func.date(Notificacion.fecha_creacion) == hoy
        ).first()

        if ya_existe:
            return

        if tipo_fichada == 'ingreso':
            titulo = 'Recordatorio: Fichá tu ingreso'
            mensaje = f'Tenés tareas activas hoy ({tareas_str}). Recordá fichar tu ingreso.'
        else:
            titulo = 'Recordatorio: Fichá tu egreso'
            mensaje = 'Ya fichaste ingreso pero no registraste la salida. Recordá fichar tu egreso.'

        notif = Notificacion(
            usuario_id=usuario_id,
            organizacion_id=org_id,
            tipo=f'fichada_{tipo_fichada}_pendiente',
            titulo=titulo,
            mensaje=mensaje,
            url='/fichadas/',
        )
        db.session.add(notif)
        db.session.commit()
    except Exception:
        db.session.rollback()


def obtener_alertas_movimientos_caja(org_id, limite=5):
    """Alertas de movimientos de caja recientes (últimas 48 horas)."""
    try:
        from models.templates import MovimientoCaja
        from datetime import datetime, timedelta

        hace_48h = datetime.utcnow() - timedelta(hours=48)
        movimientos = MovimientoCaja.query.filter(
            MovimientoCaja.organizacion_id == org_id,
            MovimientoCaja.created_at >= hace_48h,
            MovimientoCaja.estado == 'confirmado'
        ).order_by(MovimientoCaja.created_at.desc()).limit(limite).all()

        alertas = []
        for m in movimientos:
            es_gasto = m.tipo in ('gasto_obra', 'pago_proveedor')
            obra_nombre = m.obra.nombre if m.obra else 'Sin obra'
            monto_str = '${:,.0f}'.format(float(m.monto or 0))
            alertas.append({
                'tipo': 'caja',
                'severidad': 'media' if es_gasto else 'baja',
                'titulo': f'{"Gasto" if es_gasto else "Transferencia"}: {monto_str}',
                'detalle': f'{m.concepto or m.tipo} - {obra_nombre}',
                'fecha': m.created_at,
                'icono': 'fa-cash-register',
                'color': 'danger' if es_gasto else 'success',
            })
        return alertas
    except Exception:
        return []


def obtener_alertas_entregas_proximas(org_id, limite=5):
    """Alertas de entregas de OC: vencidas (sin recibir) + próximas (≤7 días).

    Cubre 2 casos que el PM/Admin necesita ver en el dashboard:
      - OC vencida: fecha_entrega_estimada pasó y sigue sin completar
        recepción. Severidad crítica — probablemente hay que llamar al
        proveedor o recepcionar lo que llegó.
      - OC próxima: entrega en los próximos 7 días. Severidad media/alta.
    """
    try:
        from models.inventory import OrdenCompra
        from datetime import date, timedelta

        hoy = date.today()
        en_7_dias = hoy + timedelta(days=7)

        ocs = OrdenCompra.query.filter(
            OrdenCompra.organizacion_id == org_id,
            OrdenCompra.estado.in_(['emitida', 'recibida_parcial']),
            OrdenCompra.fecha_entrega_estimada.isnot(None),
            OrdenCompra.fecha_entrega_estimada <= en_7_dias,
        ).order_by(OrdenCompra.fecha_entrega_estimada).limit(limite).all()

        alertas = []
        for oc in ocs:
            dias = (oc.fecha_entrega_estimada - hoy).days
            obra_nombre = oc.obra.nombre if oc.obra else 'Sin obra'

            if dias < 0:
                # Vencida (no recibida aún)
                severidad = 'critica'
                titulo = f'Entrega vencida: {oc.numero} (hace {abs(dias)} día{"s" if abs(dias) != 1 else ""})'
                color = 'danger'
            elif dias == 0:
                severidad = 'alta'
                titulo = f'Entrega HOY: {oc.numero}'
                color = 'warning'
            elif dias <= 2:
                severidad = 'alta'
                titulo = f'Entrega {oc.numero} en {dias} día(s)'
                color = 'warning'
            else:
                severidad = 'media'
                titulo = f'Entrega {oc.numero} en {dias} día(s)'
                color = 'info'

            alertas.append({
                'tipo': 'entrega_material',
                'severidad': severidad,
                'titulo': titulo,
                'detalle': f'{oc.proveedor} → {obra_nombre}',
                'fecha': oc.fecha_entrega_estimada,
                'icono': 'fa-truck',
                'color': color,
                'url': f'/ordenes-compra/{oc.id}/recepcion',
            })
        return alertas
    except Exception:
        return []


def obtener_todas_alertas(org_id, limite_por_tipo=3):
    """
    Obtiene todas las alertas del sistema agrupadas y ordenadas por severidad.
    """
    alertas = []

    # Obtener alertas de cada tipo
    alertas.extend(obtener_alertas_stock_bajo(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_presupuestos_vencer(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_obras_demoradas(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_etapas_demoradas(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_tareas_vencidas(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_tareas_en_riesgo(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_sobrecosto(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_fichadas(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_liquidaciones_pendientes(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_equipos_transito(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_movimientos_caja(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_entregas_proximas(org_id, limite_por_tipo))

    # Ordenar por severidad
    orden_severidad = {'critica': 0, 'alta': 1, 'media': 2, 'baja': 3}
    alertas.sort(key=lambda x: orden_severidad.get(x['severidad'], 3))

    return alertas


def contar_alertas_por_severidad(org_id):
    """
    Cuenta alertas agrupadas por severidad.
    """
    alertas = obtener_todas_alertas(org_id, limite_por_tipo=100)

    conteo = {'critica': 0, 'alta': 0, 'media': 0, 'total': 0}

    for alerta in alertas:
        severidad = alerta.get('severidad', 'media')
        if severidad in conteo:
            conteo[severidad] += 1
        conteo['total'] += 1

    return conteo


def obtener_alertas_para_dashboard(org_id, limite=10):
    """
    Obtiene alertas formateadas para mostrar en el dashboard.
    """
    alertas = obtener_todas_alertas(org_id, limite_por_tipo=5)

    # Limitar total
    return alertas[:limite]


def obtener_alertas_liquidaciones_pendientes(org_id, limite=5):
    """Alertas de liquidaciones MO pendientes de pago."""
    try:
        from models.templates import LiquidacionMO, LiquidacionMOItem

        pendientes = (
            db.session.query(
                LiquidacionMOItem.id,
                LiquidacionMOItem.monto,
                LiquidacionMOItem.operario_id,
                LiquidacionMO.obra_id,
                LiquidacionMO.periodo_desde,
                LiquidacionMO.periodo_hasta,
            )
            .join(LiquidacionMO)
            .filter(
                LiquidacionMO.organizacion_id == org_id,
                LiquidacionMOItem.estado == 'pendiente',
            )
            .all()
        )

        if not pendientes:
            return []

        total_monto = sum(float(p.monto or 0) for p in pendientes)
        cant = len(pendientes)

        # Obtener nombres de obras
        from models import Obra
        obra_ids = set(p.obra_id for p in pendientes)
        obras_nombres = []
        for oid in list(obra_ids)[:3]:
            obra = Obra.query.get(oid)
            if obra:
                obras_nombres.append(obra.nombre)

        return [{
            'tipo': 'liquidacion_mo',
            'severidad': 'alta' if total_monto > 100000 else 'media',
            'titulo': f'{cant} pago{"s" if cant > 1 else ""} de MO pendiente{"s" if cant > 1 else ""}',
            'descripcion': f'Total: ${total_monto:,.0f} - {", ".join(obras_nombres)}',
            'accion_url': None,
            'icono': 'fas fa-hand-holding-usd',
            'color': 'warning',
        }]
    except Exception:
        return []


def obtener_alertas_equipos_transito(org_id, limite=5):
    """Alertas de equipos en tránsito pendientes de recepción."""
    try:
        from models.equipment import EquipmentMovement
        from models import Obra

        pendientes = EquipmentMovement.query.filter_by(
            company_id=org_id,
            estado='en_transito'
        ).order_by(EquipmentMovement.fecha_movimiento.desc()).limit(limite).all()

        alertas = []
        for mov in pendientes:
            destino = mov.destino_obra.nombre if mov.destino_obra else 'Deposito'
            obra_id = mov.destino_obra_id
            alertas.append({
                'tipo': 'equipo_transito',
                'severidad': 'media',
                'icono': 'fas fa-truck',
                'titulo': f'{mov.equipment.nombre} en transito',
                'descripcion': f'Equipo {mov.equipment.nombre} ({mov.equipment.codigo or "-"}) despachado a {destino}, pendiente de recepcion',
                'obra_id': obra_id,
                'obra_nombre': destino,
                'fecha': mov.fecha_movimiento,
                'color': 'info',
            })
        return alertas
    except Exception:
        return []
