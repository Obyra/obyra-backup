"""
Servicio de alertas para el dashboard.
Genera alertas reales basadas en:
- Stock bajo de materiales
- Presupuestos por vencer
- Obras demoradas
- Tareas no completadas pasada la fecha
- Sobrecosto de obra
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy import and_, or_
from extensions import db


def obtener_alertas_stock_bajo(org_id, limite=5):
    """
    Obtiene items de inventario con stock bajo o sin stock.
    """
    from models import ItemInventario

    items = ItemInventario.query.filter(
        ItemInventario.organizacion_id == org_id,
        ItemInventario.activo == True,
        ItemInventario.stock_actual <= ItemInventario.stock_minimo
    ).order_by(ItemInventario.stock_actual).limit(limite).all()

    alertas = []
    for item in items:
        if item.stock_actual <= 0:
            severidad = 'critica'
            titulo = f'Sin stock: {item.nombre}'
        elif item.stock_actual <= (item.stock_minimo * Decimal('0.25')):
            severidad = 'alta'
            titulo = f'Stock critico: {item.nombre}'
        else:
            severidad = 'media'
            titulo = f'Stock bajo: {item.nombre}'

        alertas.append({
            'tipo': 'stock_bajo',
            'severidad': severidad,
            'titulo': titulo,
            'descripcion': f'{item.stock_actual:.0f} {item.unidad} disponibles (min: {item.stock_minimo:.0f})',
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


def obtener_alertas_sobrecosto(org_id, limite=5, umbral_porcentaje=10):
    """
    Obtiene obras con sobrecosto respecto al presupuesto.
    """
    from models import Obra

    obras = Obra.query.filter(
        Obra.organizacion_id == org_id,
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


def obtener_todas_alertas(org_id, limite_por_tipo=3):
    """
    Obtiene todas las alertas del sistema agrupadas y ordenadas por severidad.
    """
    alertas = []

    # Obtener alertas de cada tipo
    alertas.extend(obtener_alertas_stock_bajo(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_presupuestos_vencer(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_obras_demoradas(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_tareas_vencidas(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_tareas_en_riesgo(org_id, limite_por_tipo))
    alertas.extend(obtener_alertas_sobrecosto(org_id, limite_por_tipo))

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
