"""
Servicio de Alertas de Stock Bajo
Detecta items con stock bajo y genera notificaciones automáticas
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
from extensions import db
from flask import current_app


def obtener_items_stock_bajo(organizacion_id: int, incluir_sin_minimo: bool = False) -> List[Dict]:
    """
    Obtiene todos los items con stock bajo o igual al mínimo.

    Args:
        organizacion_id: ID de la organización
        incluir_sin_minimo: Si True, incluye items sin stock_minimo definido (=0)

    Returns:
        Lista de dicts con información de cada item con stock bajo
    """
    from models.inventory import ItemInventario

    query = ItemInventario.query.filter(
        ItemInventario.organizacion_id == organizacion_id,
        ItemInventario.activo == True
    )

    if not incluir_sin_minimo:
        # Solo items que tienen stock_minimo configurado (> 0)
        query = query.filter(ItemInventario.stock_minimo > 0)

    # Items donde stock_actual <= stock_minimo
    query = query.filter(ItemInventario.stock_actual <= ItemInventario.stock_minimo)

    items = query.order_by(
        (ItemInventario.stock_actual - ItemInventario.stock_minimo).asc()
    ).all()

    resultado = []
    for item in items:
        stock_actual = float(item.stock_actual or 0)
        stock_minimo = float(item.stock_minimo or 0)
        deficit = max(0, stock_minimo - stock_actual)

        # Calcular nivel de urgencia
        if stock_actual == 0:
            urgencia = 'critico'
            urgencia_color = 'danger'
        elif stock_actual <= stock_minimo * 0.25:
            urgencia = 'muy_bajo'
            urgencia_color = 'danger'
        elif stock_actual <= stock_minimo * 0.5:
            urgencia = 'bajo'
            urgencia_color = 'warning'
        else:
            urgencia = 'alerta'
            urgencia_color = 'info'

        resultado.append({
            'id': item.id,
            'codigo': item.codigo,
            'nombre': item.nombre,
            'categoria': item.categoria.nombre if item.categoria else 'Sin categoría',
            'unidad': item.unidad,
            'stock_actual': stock_actual,
            'stock_minimo': stock_minimo,
            'deficit': deficit,
            'urgencia': urgencia,
            'urgencia_color': urgencia_color,
            'precio_promedio': float(item.precio_promedio or 0),
            'costo_reposicion': deficit * float(item.precio_promedio or 0)
        })

    return resultado


def contar_alertas_stock(organizacion_id: int) -> Dict:
    """
    Cuenta las alertas de stock agrupadas por urgencia.

    Returns:
        Dict con conteo por nivel de urgencia
    """
    from models.inventory import ItemInventario

    # Items con stock_minimo definido y stock bajo
    items_bajo = ItemInventario.query.filter(
        ItemInventario.organizacion_id == organizacion_id,
        ItemInventario.activo == True,
        ItemInventario.stock_minimo > 0,
        ItemInventario.stock_actual <= ItemInventario.stock_minimo
    ).all()

    conteo = {
        'total': 0,
        'critico': 0,  # stock = 0
        'muy_bajo': 0,  # stock <= 25% del mínimo
        'bajo': 0,      # stock <= 50% del mínimo
        'alerta': 0     # stock <= mínimo
    }

    for item in items_bajo:
        stock_actual = float(item.stock_actual or 0)
        stock_minimo = float(item.stock_minimo or 0)

        conteo['total'] += 1

        if stock_actual == 0:
            conteo['critico'] += 1
        elif stock_actual <= stock_minimo * 0.25:
            conteo['muy_bajo'] += 1
        elif stock_actual <= stock_minimo * 0.5:
            conteo['bajo'] += 1
        else:
            conteo['alerta'] += 1

    return conteo


def crear_notificacion_stock_bajo(item, usuario_id: int, organizacion_id: int) -> Optional[int]:
    """
    Crea una notificación de stock bajo para un item.
    Evita duplicados verificando si ya existe una notificación reciente (últimas 24hs).

    Returns:
        ID de la notificación creada o None si ya existía una reciente
    """
    from models.core import Notificacion

    # Verificar si ya existe una notificación reciente para este item
    hace_24hs = datetime.utcnow() - timedelta(hours=24)

    notif_existente = Notificacion.query.filter(
        Notificacion.organizacion_id == organizacion_id,
        Notificacion.tipo == 'stock_bajo',
        Notificacion.referencia_tipo == 'item_inventario',
        Notificacion.referencia_id == item.id,
        Notificacion.fecha_creacion >= hace_24hs
    ).first()

    if notif_existente:
        return None

    stock_actual = float(item.stock_actual or 0)
    stock_minimo = float(item.stock_minimo or 0)

    if stock_actual == 0:
        titulo = f"⚠️ SIN STOCK: {item.nombre}"
        mensaje = f"El item '{item.nombre}' ({item.codigo}) se ha quedado sin stock. Stock mínimo requerido: {stock_minimo} {item.unidad}"
    else:
        titulo = f"📉 Stock bajo: {item.nombre}"
        mensaje = f"El item '{item.nombre}' ({item.codigo}) tiene stock bajo. Actual: {stock_actual} {item.unidad}, Mínimo: {stock_minimo} {item.unidad}"

    notif = Notificacion(
        organizacion_id=organizacion_id,
        usuario_id=usuario_id,
        tipo='stock_bajo',
        titulo=titulo,
        mensaje=mensaje,
        url=f'/inventario/{item.id}',
        referencia_tipo='item_inventario',
        referencia_id=item.id
    )

    db.session.add(notif)
    db.session.commit()

    return notif.id


def verificar_y_notificar_stock_bajo(item, usuario_id: int, organizacion_id: int) -> bool:
    """
    Verifica si un item tiene stock bajo y crea notificación si es necesario.
    Llamar después de cada movimiento de inventario.

    Returns:
        True si se creó una notificación
    """
    if not item.stock_minimo or float(item.stock_minimo) <= 0:
        return False

    if float(item.stock_actual or 0) <= float(item.stock_minimo):
        notif_id = crear_notificacion_stock_bajo(item, usuario_id, organizacion_id)
        return notif_id is not None

    return False


def generar_alertas_masivas(organizacion_id: int, usuario_id: int) -> Dict:
    """
    Genera notificaciones para todos los items con stock bajo.
    Útil para ejecutar en batch o al iniciar sesión.

    Returns:
        Dict con estadísticas de alertas generadas
    """
    from models.inventory import ItemInventario

    items_bajo = ItemInventario.query.filter(
        ItemInventario.organizacion_id == organizacion_id,
        ItemInventario.activo == True,
        ItemInventario.stock_minimo > 0,
        ItemInventario.stock_actual <= ItemInventario.stock_minimo
    ).all()

    stats = {
        'items_revisados': len(items_bajo),
        'notificaciones_creadas': 0,
        'ya_notificados': 0
    }

    for item in items_bajo:
        notif_id = crear_notificacion_stock_bajo(item, usuario_id, organizacion_id)
        if notif_id:
            stats['notificaciones_creadas'] += 1
        else:
            stats['ya_notificados'] += 1

    return stats


def obtener_resumen_alertas(organizacion_id: int) -> Dict:
    """
    Obtiene un resumen completo de alertas de stock para mostrar en dashboard.

    Returns:
        Dict con resumen de alertas, items críticos y costo de reposición
    """
    items = obtener_items_stock_bajo(organizacion_id)
    conteo = contar_alertas_stock(organizacion_id)

    # Calcular costo total de reposición
    costo_total = sum(item['costo_reposicion'] for item in items)

    # Items más críticos (top 5)
    items_criticos = [i for i in items if i['urgencia'] in ('critico', 'muy_bajo')][:5]

    return {
        'conteo': conteo,
        'costo_reposicion_total': costo_total,
        'items_criticos': items_criticos,
        'todos_los_items': items
    }
