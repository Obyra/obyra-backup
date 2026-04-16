"""Servicio de Liquidación de Mano de Obra.

Calcula horas de avance y fichadas por operario para un período dado,
y gestiona la creación/pago de liquidaciones.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask_login import current_user

from extensions import db
from models import (
    Obra, EtapaObra, TareaEtapa, TareaAvance, AsignacionObra,
    Usuario, ItemPresupuesto,
)
from models.templates import LiquidacionMO, LiquidacionMOItem


def _decimal(val, default='0'):
    try:
        return Decimal(str(val or default))
    except Exception:
        return Decimal(default)


def _q2(val):
    return val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def obtener_tarifa_default_obra(obra):
    """Obtiene tarifa/hora default del presupuesto de MO de la obra.

    Busca items de presupuesto tipo 'mano_obra' y calcula tarifa promedio.
    Si unidad es 'jornal', divide por 8h.
    """
    try:
        presupuesto = obra.presupuestos[0] if obra.presupuestos else None
        if not presupuesto:
            return Decimal('0')

        items_mo = ItemPresupuesto.query.filter_by(
            presupuesto_id=presupuesto.id,
            tipo='mano_obra'
        ).all()

        if not items_mo:
            return Decimal('0')

        total_costo = Decimal('0')
        total_jornales = Decimal('0')
        for item in items_mo:
            precio = _decimal(item.price_unit_ars) or _decimal(item.precio_unitario)
            cantidad = _decimal(item.cantidad)
            if precio > 0 and cantidad > 0:
                total_costo += precio * cantidad
                total_jornales += cantidad

        if total_jornales > 0:
            tarifa_jornal = total_costo / total_jornales
            # Jornal = 8 horas
            return _q2(tarifa_jornal / Decimal('8'))

        return Decimal('0')
    except Exception:
        return Decimal('0')


def calcular_horas_avance_operario(obra_id, operario_id, desde, hasta):
    """Calcula horas de avances aprobados de un operario en un período.

    Returns: dict con horas totales y desglose por tarea.
    """
    avances = (
        TareaAvance.query
        .join(TareaEtapa, TareaAvance.tarea_id == TareaEtapa.id)
        .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)
        .filter(
            EtapaObra.obra_id == obra_id,
            TareaAvance.user_id == operario_id,
            TareaAvance.status == 'aprobado',
            TareaAvance.fecha >= desde,
            TareaAvance.fecha <= hasta,
        )
        .all()
    )

    total_horas = Decimal('0')
    desglose = []
    for av in avances:
        h = _decimal(av.horas) or _decimal(av.horas_trabajadas)
        total_horas += h
        desglose.append({
            'tarea': av.tarea.nombre if av.tarea else 'N/A',
            'etapa': av.tarea.etapa.nombre if av.tarea and av.tarea.etapa else 'N/A',
            'horas': float(h),
            'cantidad': float(av.cantidad or 0),
            'unidad': av.unidad or '',
            'fecha': av.fecha.isoformat() if av.fecha else '',
        })

    return {
        'total_horas': float(total_horas),
        'desglose': desglose,
    }


def calcular_horas_fichadas_operario(obra_id, operario_id, desde, hasta):
    """Calcula horas fichadas (ingreso/egreso) de un operario en un período.

    Returns: dict con horas totales y desglose por día.
    """
    from models.projects import Fichada

    fichadas = (
        Fichada.query
        .filter(
            Fichada.obra_id == obra_id,
            Fichada.usuario_id == operario_id,
            db.func.date(Fichada.fecha_hora) >= desde,
            db.func.date(Fichada.fecha_hora) <= hasta,
        )
        .order_by(Fichada.fecha_hora.asc())
        .all()
    )

    # Agrupar por día
    from collections import defaultdict
    por_dia = defaultdict(list)
    for f in fichadas:
        dia = f.fecha_hora.date()
        por_dia[dia].append(f)

    total_segundos = 0
    desglose = []
    for dia, fichs in sorted(por_dia.items()):
        # Emparejar ingreso/egreso por timestamp (no por índice posicional)
        # Ordenar cronológicamente
        fichs_sorted = sorted(fichs, key=lambda f: f.fecha_hora)
        segundos_dia = 0
        primer_ingreso = None
        ultimo_egreso = None
        egresos_usados = set()

        ingresos = [f for f in fichs_sorted if f.tipo == 'ingreso']
        egresos = [f for f in fichs_sorted if f.tipo == 'egreso']

        for ing in ingresos:
            if not primer_ingreso:
                primer_ingreso = ing
            # Buscar el egreso más cercano POSTERIOR a este ingreso que no esté usado
            mejor_egr = None
            for egr in egresos:
                if egr.id in egresos_usados:
                    continue
                if egr.fecha_hora > ing.fecha_hora:
                    mejor_egr = egr
                    break  # El primero posterior es el más cercano (ya están ordenados)
            if mejor_egr:
                egresos_usados.add(mejor_egr.id)
                diff = (mejor_egr.fecha_hora - ing.fecha_hora).total_seconds()
                if 0 < diff <= 86400:  # Máximo 24hs por par (previene errores)
                    segundos_dia += diff
                    ultimo_egreso = mejor_egr

        total_segundos += segundos_dia
        horas_dia = round(segundos_dia / 3600, 2)

        if horas_dia > 0 or fichs:
            ingreso_str = primer_ingreso.fecha_hora.strftime('%H:%M') if primer_ingreso else '-'
            egreso_str = ultimo_egreso.fecha_hora.strftime('%H:%M') if ultimo_egreso else '-'
            desglose.append({
                'fecha': dia.isoformat(),
                'ingreso': ingreso_str,
                'egreso': egreso_str,
                'horas': horas_dia,
            })

    return {
        'total_horas': round(total_segundos / 3600, 2),
        'desglose': desglose,
    }


def calcular_cantidad_avance_operario(obra_id, operario_id, desde, hasta):
    """Suma la cantidad (m², u, etc.) ejecutada por un operario desde sus avances aprobados."""
    avances = (
        TareaAvance.query
        .join(TareaEtapa, TareaAvance.tarea_id == TareaEtapa.id)
        .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)
        .filter(
            EtapaObra.obra_id == obra_id,
            TareaAvance.user_id == operario_id,
            TareaAvance.status == 'aprobado',
            TareaAvance.fecha >= desde,
            TareaAvance.fecha <= hasta,
        )
        .all()
    )
    total_cantidad = Decimal('0')
    unidades = set()
    for av in avances:
        total_cantidad += _decimal(av.cantidad)
        if av.unidad:
            unidades.add(av.unidad)
    # Unidad dominante: si todas iguales usar esa, si hay mixtas retornar la más común o vacía
    unidad = list(unidades)[0] if len(unidades) == 1 else ('m2' if 'm2' in unidades else (list(unidades)[0] if unidades else ''))
    return {'cantidad': total_cantidad, 'unidad': unidad}


def calcular_liquidacion_por_operario(operario, obra_id, desde, hasta, tarifa_fallback=None):
    """Calcula liquidación de un operario según su modalidad de pago configurada.

    Retorna un dict con:
      - modalidad: 'medida' | 'hora' | 'fichada'
      - base: cantidad numérica (m² ó h)
      - unidad: 'm2' | 'h'
      - tarifa: precio unitario
      - monto: base × tarifa (Decimal cuantizado)
      - warning: mensaje si falta tarifa o base
    """
    modalidad = (operario.modalidad_pago or 'hora').lower()
    tarifa_hora_user = _decimal(operario.tarifa_hora)
    tarifa_m2_user = _decimal(operario.tarifa_m2)
    tarifa_fallback = _decimal(tarifa_fallback) if tarifa_fallback is not None else Decimal('0')

    warning = None

    if modalidad == 'medida':
        avance = calcular_cantidad_avance_operario(obra_id, operario.id, desde, hasta)
        cantidad = avance['cantidad']
        unidad = avance['unidad'] or 'm2'
        tarifa = tarifa_m2_user
        if tarifa <= 0:
            warning = 'Operario en modalidad medida sin tarifa $/m² configurada'
        monto = _q2(cantidad * tarifa) if tarifa > 0 else Decimal('0')
        return {
            'modalidad': 'medida',
            'base': float(cantidad),
            'unidad': unidad,
            'tarifa': float(tarifa),
            'monto': float(monto),
            'warning': warning,
        }

    if modalidad == 'fichada':
        fich = calcular_horas_fichadas_operario(obra_id, operario.id, desde, hasta)
        horas = _decimal(fich['total_horas'])
        tarifa = tarifa_hora_user if tarifa_hora_user > 0 else tarifa_fallback
        if tarifa <= 0:
            warning = 'Operario en modalidad fichada sin tarifa $/h configurada'
        monto = _q2(horas * tarifa) if tarifa > 0 else Decimal('0')
        return {
            'modalidad': 'fichada',
            'base': float(horas),
            'unidad': 'h',
            'tarifa': float(tarifa),
            'monto': float(monto),
            'warning': warning,
        }

    # 'hora' (default): horas de avance aprobado × tarifa/h
    av = calcular_horas_avance_operario(obra_id, operario.id, desde, hasta)
    horas = _decimal(av['total_horas'])
    tarifa = tarifa_hora_user if tarifa_hora_user > 0 else tarifa_fallback
    if tarifa <= 0:
        warning = 'Operario en modalidad hora sin tarifa $/h configurada'
    monto = _q2(horas * tarifa) if tarifa > 0 else Decimal('0')
    return {
        'modalidad': 'hora',
        'base': float(horas),
        'unidad': 'h',
        'tarifa': float(tarifa),
        'monto': float(monto),
        'warning': warning,
    }


def buscar_operarios_obra(obra_id, desde, hasta):
    """Busca todos los operarios que trabajaron en la obra en el período.

    Combina: asignaciones de obra + avances registrados + fichadas.
    """
    operarios = {}

    # 1. Asignaciones activas
    asignaciones = AsignacionObra.query.filter_by(obra_id=obra_id, activo=True).all()
    for asig in asignaciones:
        if asig.usuario and asig.usuario_id not in operarios:
            operarios[asig.usuario_id] = asig.usuario

    # 2. Operarios con avances en el período
    avance_users = (
        db.session.query(TareaAvance.user_id)
        .join(TareaEtapa, TareaAvance.tarea_id == TareaEtapa.id)
        .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)
        .filter(
            EtapaObra.obra_id == obra_id,
            TareaAvance.status == 'aprobado',
            TareaAvance.fecha >= desde,
            TareaAvance.fecha <= hasta,
        )
        .distinct()
        .all()
    )
    for (uid,) in avance_users:
        if uid and uid not in operarios:
            u = Usuario.query.get(uid)
            if u:
                operarios[uid] = u

    # 3. Operarios con fichadas en el período
    from models.projects import Fichada
    fichada_users = (
        db.session.query(Fichada.usuario_id)
        .filter(
            Fichada.obra_id == obra_id,
            db.func.date(Fichada.fecha_hora) >= desde,
            db.func.date(Fichada.fecha_hora) <= hasta,
        )
        .distinct()
        .all()
    )
    for (uid,) in fichada_users:
        if uid and uid not in operarios:
            u = Usuario.query.get(uid)
            if u:
                operarios[uid] = u

    return operarios


def generar_preview_liquidacion(obra_id, desde, hasta):
    """Genera preview de liquidación sin guardar.

    Returns: lista de items con datos calculados por operario.
    """
    obra = Obra.query.get(obra_id)
    if not obra:
        return []

    tarifa_default = obtener_tarifa_default_obra(obra)
    operarios = buscar_operarios_obra(obra_id, desde, hasta)

    items = []
    for uid, usuario in operarios.items():
        avance_data = calcular_horas_avance_operario(obra_id, uid, desde, hasta)
        fichada_data = calcular_horas_fichadas_operario(obra_id, uid, desde, hasta)

        horas_avance = avance_data['total_horas']
        horas_fichadas = fichada_data['total_horas']

        # Cálculo por modalidad configurada en el usuario
        modalidad_data = calcular_liquidacion_por_operario(
            usuario, obra_id, desde, hasta, tarifa_fallback=tarifa_default
        )

        # Obtener rol en obra
        asig = AsignacionObra.query.filter_by(
            obra_id=obra_id, usuario_id=uid, activo=True
        ).first()

        items.append({
            'operario_id': uid,
            'operario_nombre': usuario.nombre_completo,
            'rol': asig.rol_en_obra if asig else 'sin asignar',
            'modalidad': modalidad_data['modalidad'],
            'base': modalidad_data['base'],
            'unidad': modalidad_data['unidad'],
            'horas_avance': horas_avance,
            'horas_fichadas': horas_fichadas,
            'horas_liquidar': modalidad_data['base'] if modalidad_data['unidad'] == 'h' else 0,
            'tarifa_hora': modalidad_data['tarifa'],
            'monto': modalidad_data['monto'],
            'warning': modalidad_data.get('warning'),
            'avance_desglose': avance_data['desglose'],
            'fichada_desglose': fichada_data['desglose'],
            'diferencia_horas': round(horas_fichadas - horas_avance, 2),
        })

    # Ordenar por nombre
    items.sort(key=lambda x: x['operario_nombre'])
    return items


def generar_preview_unificado(obra_id, desde, hasta):
    """Genera preview unificado: etapas → operarios → detalle.

    Combina compute_etapa_breakdown (cert. cliente) con detalle de
    operarios por etapa (liquidación MO).
    """
    obra = Obra.query.get(obra_id)
    if not obra:
        return {'etapas': [], 'operarios_sin_etapa': []}

    from services.certifications import compute_etapa_breakdown
    from models.projects import EtapaObra

    tarifa_default = obtener_tarifa_default_obra(obra)
    operarios = buscar_operarios_obra(obra_id, desde, hasta)
    etapa_breakdown = compute_etapa_breakdown(obra)

    # Nota: NO filtramos operarios ya liquidados. El admin puede querer
    # liquidar diferencias o tareas nuevas completadas en el mismo período.
    # El historial de liquidaciones muestra qué ya se pagó.

    # Calcular avance por conteo simple de tareas (igual que cronograma)
    def _pct_etapa_simple(etapa_id):
        etapa = EtapaObra.query.get(etapa_id)
        if not etapa:
            return 0
        tareas = etapa.tareas.all() if hasattr(etapa.tareas, 'all') else (etapa.tareas or [])
        if not tareas:
            return 0
        completadas = sum(1 for t in tareas if t.estado in ('completada', 'finalizada'))
        return round((completadas / len(tareas)) * 100, 2)

    pct_simple_map = {ei['etapa_id']: _pct_etapa_simple(ei['etapa_id']) for ei in (etapa_breakdown.get('etapas') or [])}

    # Calcular datos de cada operario
    operarios_data = {}
    for uid, usuario in operarios.items():
        avance_data = calcular_horas_avance_operario(obra_id, uid, desde, hasta)
        fichada_data = calcular_horas_fichadas_operario(obra_id, uid, desde, hasta)

        asig = AsignacionObra.query.filter_by(
            obra_id=obra_id, usuario_id=uid, activo=True
        ).first()

        # Cálculo según modalidad configurada del operario
        modalidad_data = calcular_liquidacion_por_operario(
            usuario, obra_id, desde, hasta, tarifa_fallback=tarifa_default
        )

        operarios_data[uid] = {
            'operario_id': uid,
            'operario_nombre': usuario.nombre_completo,
            'rol': asig.rol_en_obra if asig else 'operario',
            'horas_fichadas': fichada_data['total_horas'],
            'fichada_desglose': fichada_data['desglose'],
            'avance_desglose': avance_data['desglose'],
            'horas_avance_total': avance_data['total_horas'],
            'modalidad': modalidad_data['modalidad'],
            'tarifa_hora_user': float(_decimal(usuario.tarifa_hora)),
            'tarifa_m2_user': float(_decimal(usuario.tarifa_m2)),
            'modalidad_base': modalidad_data['base'],
            'modalidad_unidad': modalidad_data['unidad'],
            'modalidad_tarifa': modalidad_data['tarifa'],
            'modalidad_monto': modalidad_data['monto'],
            'modalidad_warning': modalidad_data.get('warning'),
        }

    # Agrupar avances por etapa → operario
    # avance_desglose items tienen 'etapa' y 'tarea'
    etapa_operarios = {}  # etapa_nombre -> {uid -> [tareas]}
    for uid, op_data in operarios_data.items():
        for av in op_data['avance_desglose']:
            etapa_nombre = av.get('etapa', 'Sin etapa')
            if etapa_nombre not in etapa_operarios:
                etapa_operarios[etapa_nombre] = {}
            if uid not in etapa_operarios[etapa_nombre]:
                etapa_operarios[etapa_nombre][uid] = []
            etapa_operarios[etapa_nombre][uid].append(av)

    # Etapas con avances pero sin costo presupuestado — agregar con costo=0 para
    # que los operarios que trabajaron igual aparezcan en el preview.
    etapas_en_breakdown = {ei['etapa_nombre'] for ei in (etapa_breakdown.get('etapas') or [])}
    etapas_extras = []
    for etapa_nombre_av in etapa_operarios.keys():
        if etapa_nombre_av in etapas_en_breakdown:
            continue
        # Buscar la etapa por nombre para conseguir id y porcentaje
        etapa_obj = EtapaObra.query.filter_by(obra_id=obra_id, nombre=etapa_nombre_av).first()
        eid = etapa_obj.id if etapa_obj else None
        tareas_total = 0
        tareas_completadas = 0
        if etapa_obj:
            tareas_all = etapa_obj.tareas.all() if hasattr(etapa_obj.tareas, 'all') else (etapa_obj.tareas or [])
            tareas_total = len(tareas_all)
            tareas_completadas = sum(1 for t in tareas_all if t.estado in ('completada', 'finalizada'))
        etapas_extras.append({
            'etapa_id': eid,
            'etapa_nombre': etapa_nombre_av,
            'porcentaje_avance': _pct_etapa_simple(eid) if eid else 0,
            'costo_presupuestado': Decimal('0'),
            'monto_certificable': Decimal('0'),
            'tareas_total': tareas_total,
            'tareas_completadas': tareas_completadas,
        })

    # Construir resultado por etapa
    etapas_result = []
    operarios_usados = set()

    for etapa_info in list(etapa_breakdown.get('etapas') or []) + etapas_extras:
        etapa_nombre = etapa_info['etapa_nombre']
        ops_en_etapa = etapa_operarios.get(etapa_nombre, {})

        operarios_list = []
        subtotal_mo = Decimal('0')

        for uid, tareas in ops_en_etapa.items():
            op = operarios_data.get(uid)
            if not op:
                continue
            operarios_usados.add(uid)

            # Horas avance en ESTA etapa
            horas_avance_etapa = sum(t.get('horas', 0) for t in tareas)
            # Cantidad total en esta etapa
            cantidad_total = sum(t.get('cantidad', 0) for t in tareas)
            unidades = set(t.get('unidad', '') for t in tareas if t.get('unidad'))
            unidad = list(unidades)[0] if len(unidades) == 1 else ', '.join(unidades) if unidades else ''

            # Default según modalidad del operario
            modalidad = op.get('modalidad') or 'hora'
            if modalidad == 'medida':
                tarifa = op.get('tarifa_m2_user') or 0
                monto_default = float(_q2(_decimal(cantidad_total) * _decimal(tarifa)))
            elif modalidad == 'fichada':
                tarifa = op.get('tarifa_hora_user') or float(tarifa_default)
                monto_default = float(_q2(_decimal(op['horas_fichadas']) * _decimal(tarifa)))
            else:  # 'hora' (default)
                tarifa = op.get('tarifa_hora_user') or float(tarifa_default)
                horas_liquidar = horas_avance_etapa if horas_avance_etapa > 0 else op['horas_fichadas']
                monto_default = float(_q2(_decimal(horas_liquidar) * _decimal(tarifa)))

            operarios_list.append({
                'operario_id': uid,
                'operario_nombre': op['operario_nombre'],
                'rol': op['rol'],
                'modalidad': modalidad,
                'tarifa_m2_user': op.get('tarifa_m2_user', 0),
                'tarifa_hora_user': op.get('tarifa_hora_user', 0),
                'tareas': tareas,
                'cantidad_total': cantidad_total,
                'unidad': unidad,
                'horas_avance': horas_avance_etapa,
                'horas_fichadas': op['horas_fichadas'],
                'tarifa_hora': float(tarifa),
                'monto_default': monto_default,
            })
            subtotal_mo += _decimal(monto_default)

        etapas_result.append({
            'etapa_id': etapa_info['etapa_id'],
            'etapa_nombre': etapa_nombre,
            'porcentaje_avance': pct_simple_map.get(etapa_info['etapa_id'], etapa_info.get('porcentaje_avance', 0)),
            'costo_presupuestado': float(etapa_info['costo_presupuestado'] or 0),
            'monto_certificable': float(etapa_info['monto_certificable'] or 0),
            'tareas_total': etapa_info['tareas_total'],
            'tareas_completadas': etapa_info['tareas_completadas'],
            'operarios': operarios_list,
            'subtotal_mo': float(subtotal_mo),
        })

    # Operarios con fichadas pero sin avances en ninguna etapa
    operarios_sin_etapa = []
    for uid, op in operarios_data.items():
        if uid not in operarios_usados and op['horas_fichadas'] > 0:
            modalidad = op.get('modalidad') or 'hora'
            tarifa = op.get('tarifa_hora_user') or float(tarifa_default)
            monto_default = float(_q2(_decimal(op['horas_fichadas']) * _decimal(tarifa)))
            operarios_sin_etapa.append({
                'operario_id': uid,
                'operario_nombre': op['operario_nombre'],
                'rol': op['rol'],
                'modalidad': modalidad,
                'tarifa_m2_user': op.get('tarifa_m2_user', 0),
                'tarifa_hora_user': op.get('tarifa_hora_user', 0),
                'tareas': [],
                'cantidad_total': 0,
                'unidad': '',
                'horas_avance': 0,
                'horas_fichadas': op['horas_fichadas'],
                'fichada_desglose': op['fichada_desglose'],
                'tarifa_hora': float(tarifa),
                'monto_default': monto_default,
            })

    return {
        'etapas': etapas_result,
        'operarios_sin_etapa': operarios_sin_etapa,
        'tarifa_default': float(tarifa_default),
        'ya_certificado_ars': float(etapa_breakdown.get('ya_certificado_ars', 0)),
        'presupuesto_total': float(etapa_breakdown.get('presupuesto_total', 0)),
        'total_certificable': float(etapa_breakdown.get('total_certificable', 0)),
    }


def generar_liquidacion_desde_fichadas(obra_id, desde, hasta, notas=None, commit=True):
    """Genera automaticamente una LiquidacionMO a partir de fichadas aprobadas.

    Lee las fichadas del periodo + obra, agrupa por operario, calcula horas
    contra la tarifa default de la obra y crea la liquidacion en un solo paso.
    No requiere preview ni edicion manual.

    Args:
        obra_id: ID de la obra
        desde, hasta: fechas del periodo (date)
        notas: notas opcionales
        commit: si True hace commit inmediato

    Returns:
        tuple (LiquidacionMO, dict con resumen) o (None, dict con error)
    """
    obra = Obra.query.get(obra_id)
    if not obra:
        return None, {'error': 'Obra no encontrada'}

    tarifa_default = obtener_tarifa_default_obra(obra)
    if tarifa_default <= 0:
        return None, {'error': 'No se pudo determinar la tarifa hora. Configura el costo de mano de obra en el presupuesto.'}

    operarios = buscar_operarios_obra(obra_id, desde, hasta)
    if not operarios:
        return None, {'error': 'No hay operarios con fichadas/avances en el periodo seleccionado'}

    items_data = []
    operarios_sin_horas = []
    for uid, usuario in operarios.items():
        fichada_data = calcular_horas_fichadas_operario(obra_id, uid, desde, hasta)
        horas = fichada_data['total_horas']
        if horas <= 0:
            operarios_sin_horas.append(usuario.nombre_completo)
            continue

        monto = _q2(_decimal(horas) * tarifa_default)
        items_data.append({
            'operario_id': uid,
            'horas_liquidadas': float(horas),
            'tarifa_hora': float(tarifa_default),
            'monto': float(monto),
        })

    if not items_data:
        return None, {'error': 'Ningun operario tiene fichadas registradas en el periodo'}

    liq = crear_liquidacion(obra_id, desde, hasta, items_data, notas=notas, commit=commit)
    return liq, {
        'operarios_liquidados': len(items_data),
        'operarios_sin_horas': operarios_sin_horas,
        'tarifa_hora': float(tarifa_default),
        'monto_total': float(liq.monto_total),
    }


def crear_liquidacion(obra_id, desde, hasta, items_data, notas=None, commit=True):
    """Crea una liquidación con sus items.

    Args:
        obra_id: ID de la obra
        desde, hasta: fechas del período
        items_data: lista de dicts con operario_id, horas_liquidadas, tarifa_hora, monto
        notas: notas opcionales
        commit: si True, hace commit. Si False, deja el commit al caller.

    Returns: LiquidacionMO creada
    """
    from services.memberships import get_current_org_id

    obra = Obra.query.get_or_404(obra_id)
    org_id = get_current_org_id() or obra.organizacion_id

    liq = LiquidacionMO(
        obra_id=obra_id,
        organizacion_id=org_id,
        periodo_desde=desde,
        periodo_hasta=hasta,
        estado='pendiente',
        notas=notas,
        created_by_id=current_user.id,
    )
    db.session.add(liq)
    db.session.flush()  # Obtener ID

    monto_total = Decimal('0')
    for item_data in items_data:
        operario_id = int(item_data['operario_id'])
        horas_liq = _decimal(item_data.get('horas_liquidadas', 0))
        tarifa = _decimal(item_data.get('tarifa_hora', 0))
        monto = _decimal(item_data.get('monto', 0))
        modalidad = (item_data.get('modalidad_pago') or item_data.get('modalidad') or '').lower() or None
        cantidad_liq = _decimal(item_data.get('cantidad_liquidada', 0))
        unidad_liq = item_data.get('unidad_liquidada') or item_data.get('unidad') or None

        # Si no viene modalidad explícita, inferir del usuario
        if not modalidad:
            op_user = Usuario.query.get(operario_id)
            modalidad = (op_user.modalidad_pago or 'hora') if op_user else 'hora'

        # Si monto es 0 pero hay horas y tarifa, calcular
        if monto == 0 and horas_liq > 0 and tarifa > 0:
            monto = _q2(horas_liq * tarifa)
        # Si modalidad='medida' y monto=0, calcular a partir de cantidad
        if monto == 0 and modalidad == 'medida' and cantidad_liq > 0 and tarifa > 0:
            monto = _q2(cantidad_liq * tarifa)

        # Recalcular horas informativas
        avance = calcular_horas_avance_operario(obra_id, operario_id, desde, hasta)
        fichada = calcular_horas_fichadas_operario(obra_id, operario_id, desde, hasta)

        item = LiquidacionMOItem(
            liquidacion_id=liq.id,
            operario_id=operario_id,
            horas_avance=avance['total_horas'],
            horas_fichadas=fichada['total_horas'],
            horas_liquidadas=float(horas_liq),
            tarifa_hora=float(tarifa),
            monto=float(monto),
            modalidad_pago=modalidad,
            cantidad_liquidada=float(cantidad_liq),
            unidad_liquidada=unidad_liq,
            estado='pendiente',
        )
        db.session.add(item)
        monto_total += monto

    liq.monto_total = float(monto_total)
    if commit:
        db.session.commit()

    return liq


def registrar_pago_item(item_id, metodo_pago, fecha_pago=None, comprobante_url=None, notas=None):
    """Registra el pago de un item de liquidación.

    Actualiza el costo real de la obra.
    """
    item = LiquidacionMOItem.query.get_or_404(item_id)
    item.estado = 'pagado'
    item.metodo_pago = metodo_pago
    item.fecha_pago = fecha_pago or date.today()
    item.comprobante_url = comprobante_url
    item.pagado_por_id = current_user.id
    item.pagado_at = datetime.utcnow()
    if notas:
        item.notas = notas

    # Actualizar estado de la liquidación padre
    item.liquidacion.recalcular_estado()

    # Sumar al costo real de la obra
    obra = item.liquidacion.obra
    costo_mo_pagado = _decimal(
        db.session.query(db.func.coalesce(db.func.sum(LiquidacionMOItem.monto), 0))
        .join(LiquidacionMO)
        .filter(LiquidacionMO.obra_id == obra.id, LiquidacionMOItem.estado == 'pagado')
        .scalar()
    )
    # Actualizar costo_real (MO + materiales)
    from models.inventory import ItemInventario
    from models import UsoInventario
    costo_materiales = _decimal(
        db.session.query(
            db.func.coalesce(db.func.sum(
                UsoInventario.cantidad_usada * db.func.coalesce(UsoInventario.precio_unitario_al_uso, 0)
            ), 0)
        ).filter(UsoInventario.obra_id == obra.id).scalar()
    )
    obra.costo_real = float(costo_materiales + costo_mo_pagado)

    db.session.commit()
    return item


def obtener_liquidaciones_obra(obra_id):
    """Obtiene todas las liquidaciones de una obra."""
    return (
        LiquidacionMO.query
        .filter_by(obra_id=obra_id)
        .order_by(LiquidacionMO.created_at.desc())
        .all()
    )


def alertas_liquidacion(obra_id=None, org_id=None):
    """Genera alertas para el dashboard.

    Returns: lista de alertas con tipo, mensaje, obra, etc.
    """
    alertas = []

    # Base query
    query = LiquidacionMOItem.query.join(LiquidacionMO)
    if obra_id:
        query = query.filter(LiquidacionMO.obra_id == obra_id)
    if org_id:
        query = query.filter(LiquidacionMO.organizacion_id == org_id)

    # 1. Liquidaciones pendientes de pago
    pendientes = query.filter(LiquidacionMOItem.estado == 'pendiente').all()
    if pendientes:
        total_pendiente = sum(float(p.monto or 0) for p in pendientes)
        obras_nombres = set()
        operarios_nombres = set()
        for p in pendientes:
            obras_nombres.add(p.liquidacion.obra.nombre)
            operarios_nombres.add(p.operario.nombre_completo if p.operario else 'N/A')

        alertas.append({
            'tipo': 'warning',
            'icono': 'fas fa-money-bill-wave',
            'titulo': f'{len(pendientes)} liquidaciones pendientes de pago',
            'detalle': f'Total: ${total_pendiente:,.0f} - {", ".join(operarios_nombres)}',
            'obras': list(obras_nombres),
        })

    return alertas


def alertas_operario(usuario_id):
    """Alertas para un operario específico (su dashboard)."""
    alertas = []

    # Liquidaciones pendientes (le deben plata)
    pendientes = (
        LiquidacionMOItem.query
        .filter_by(operario_id=usuario_id, estado='pendiente')
        .all()
    )
    for p in pendientes:
        alertas.append({
            'tipo': 'info',
            'icono': 'fas fa-file-invoice-dollar',
            'titulo': f'Liquidación generada: ${float(p.monto or 0):,.0f}',
            'detalle': (
                f'Obra: {p.liquidacion.obra.nombre} - '
                f'Período: {p.liquidacion.periodo_desde.strftime("%d/%m")}→'
                f'{p.liquidacion.periodo_hasta.strftime("%d/%m")}'
            ),
            'estado': 'pendiente',
        })

    # Pagos recibidos (últimos 30 días)
    desde = date.today() - timedelta(days=30)
    pagados = (
        LiquidacionMOItem.query
        .filter(
            LiquidacionMOItem.operario_id == usuario_id,
            LiquidacionMOItem.estado == 'pagado',
            LiquidacionMOItem.pagado_at >= desde,
        )
        .all()
    )
    for p in pagados:
        alertas.append({
            'tipo': 'success',
            'icono': 'fas fa-check-circle',
            'titulo': f'Pago recibido: ${float(p.monto or 0):,.0f}',
            'detalle': (
                f'Obra: {p.liquidacion.obra.nombre} - '
                f'{p.metodo_pago or "transferencia"} - '
                f'{p.fecha_pago.strftime("%d/%m/%Y") if p.fecha_pago else ""}'
            ),
            'estado': 'pagado',
        })

    return alertas
