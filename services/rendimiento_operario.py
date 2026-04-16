"""Servicio de Rendimiento de Producción por Operario.

Compara horas estimadas vs reales y rendimiento planificado vs real
para calcular eficiencia a nivel tarea, etapa, obra y global.
"""

from decimal import Decimal
from sqlalchemy import func

from extensions import db
from models import TareaEtapa, TareaAvance, EtapaObra, Obra, Usuario


def _safe_float(val, default=0):
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


def _semaforo(pct):
    if pct >= 100:
        return 'verde'
    if pct >= 80:
        return 'amarillo'
    return 'rojo'


def calcular_rendimiento_tarea(tarea_id, operario_id=None):
    """Rendimiento de operario(s) en una tarea específica.

    Si operario_id=None, agrega todos los operarios.
    Retorna dict con eficiencia y rendimiento.
    """
    tarea = TareaEtapa.query.get(tarea_id)
    if not tarea:
        return None

    h_estimadas = _safe_float(tarea.horas_estimadas)
    cant_planificada = _safe_float(tarea.cantidad_planificada)
    rend_planificado = _safe_float(tarea.rendimiento)
    unidad = tarea.unidad or ''

    # Sumar avances aprobados
    query = TareaAvance.query.filter_by(tarea_id=tarea_id, status='aprobado')
    if operario_id:
        query = query.filter_by(user_id=operario_id)

    avances = query.all()
    if not avances:
        return {
            'horas_estimadas': h_estimadas,
            'horas_reales': 0,
            'eficiencia_pct': 0,
            'cantidad_ejecutada': 0,
            'unidad': unidad,
            'rendimiento_real': 0,
            'rendimiento_plan': rend_planificado,
            'indice_rendimiento': 0,
            'semaforo': 'gris',
        }

    h_reales = sum(_safe_float(av.horas) or _safe_float(av.horas_trabajadas) for av in avances)
    cant_ejecutada = sum(_safe_float(av.cantidad) for av in avances)

    eficiencia = round((h_estimadas / h_reales) * 100, 1) if h_reales > 0 else 0
    rend_real = round(cant_ejecutada / h_reales, 2) if h_reales > 0 else 0
    indice = round((rend_real / rend_planificado) * 100, 1) if rend_planificado > 0 else 0

    return {
        'horas_estimadas': h_estimadas,
        'horas_reales': round(h_reales, 2),
        'eficiencia_pct': eficiencia,
        'cantidad_ejecutada': round(cant_ejecutada, 1),
        'unidad': unidad,
        'rendimiento_real': rend_real,
        'rendimiento_plan': rend_planificado,
        'indice_rendimiento': indice,
        'semaforo': _semaforo(eficiencia),
    }


def calcular_rendimiento_etapa(etapa_id, operario_id):
    """Rendimiento agregado de un operario en todas las tareas de una etapa."""
    etapa = EtapaObra.query.get(etapa_id)
    if not etapa:
        return None

    tareas = TareaEtapa.query.filter_by(etapa_id=etapa_id).all()
    total_h_est = 0
    total_h_real = 0
    total_cant = 0
    desglose = []

    for tarea in tareas:
        r = calcular_rendimiento_tarea(tarea.id, operario_id)
        if not r or r['horas_reales'] == 0:
            continue
        total_h_est += r['horas_estimadas']
        total_h_real += r['horas_reales']
        total_cant += r['cantidad_ejecutada']
        desglose.append({
            'tarea_id': tarea.id,
            'tarea_nombre': tarea.nombre,
            **r,
        })

    eficiencia = round((total_h_est / total_h_real) * 100, 1) if total_h_real > 0 else 0

    return {
        'etapa_id': etapa_id,
        'etapa_nombre': etapa.nombre,
        'horas_estimadas': round(total_h_est, 2),
        'horas_reales': round(total_h_real, 2),
        'eficiencia_pct': eficiencia,
        'semaforo': _semaforo(eficiencia),
        'tareas': desglose,
    }


def calcular_rendimiento_obra(obra_id, operario_id=None):
    """Rendimiento de operario(s) en una obra completa.

    Si operario_id=None, calcula por cada operario que tiene avances.
    """
    etapas = EtapaObra.query.filter_by(obra_id=obra_id).all()

    if operario_id:
        # Un solo operario
        total_h_est = 0
        total_h_real = 0
        etapas_data = []
        for etapa in etapas:
            r = calcular_rendimiento_etapa(etapa.id, operario_id)
            if r and r['horas_reales'] > 0:
                total_h_est += r['horas_estimadas']
                total_h_real += r['horas_reales']
                etapas_data.append(r)

        eficiencia = round((total_h_est / total_h_real) * 100, 1) if total_h_real > 0 else 0
        return {
            'obra_id': obra_id,
            'horas_estimadas': round(total_h_est, 2),
            'horas_reales': round(total_h_real, 2),
            'eficiencia_pct': eficiencia,
            'semaforo': _semaforo(eficiencia),
            'etapas': etapas_data,
        }

    # Todos los operarios — ranking
    return ranking_operarios_obra(obra_id)


def ranking_operarios_obra(obra_id):
    """Ranking de operarios por eficiencia en una obra."""
    # Buscar todos los operarios que tienen avances en esta obra
    operario_ids = (
        db.session.query(TareaAvance.user_id)
        .join(TareaEtapa, TareaAvance.tarea_id == TareaEtapa.id)
        .join(EtapaObra, TareaEtapa.etapa_id == EtapaObra.id)
        .filter(
            EtapaObra.obra_id == obra_id,
            TareaAvance.status == 'aprobado',
        )
        .distinct()
        .all()
    )

    ranking = []
    for (uid,) in operario_ids:
        usuario = Usuario.query.get(uid)
        if not usuario:
            continue

        total_h_est = 0
        total_h_real = 0
        total_cant = 0
        tareas_count = 0
        unidades = set()

        etapas = EtapaObra.query.filter_by(obra_id=obra_id).all()
        for etapa in etapas:
            tareas = TareaEtapa.query.filter_by(etapa_id=etapa.id).all()
            for tarea in tareas:
                avances = TareaAvance.query.filter_by(
                    tarea_id=tarea.id, user_id=uid, status='aprobado'
                ).all()
                if not avances:
                    continue
                h_est = _safe_float(tarea.horas_estimadas)
                h_real = sum(_safe_float(av.horas) or _safe_float(av.horas_trabajadas) for av in avances)
                cant = sum(_safe_float(av.cantidad) for av in avances)
                total_h_est += h_est
                total_h_real += h_real
                total_cant += cant
                tareas_count += 1
                if tarea.unidad:
                    unidades.add(tarea.unidad)

        if total_h_real == 0:
            continue

        eficiencia = round((total_h_est / total_h_real) * 100, 1)
        rend_real = round(total_cant / total_h_real, 2) if total_h_real > 0 else 0
        unidad = list(unidades)[0] if len(unidades) == 1 else 'mix'

        ranking.append({
            'operario_id': uid,
            'operario_nombre': usuario.nombre_completo,
            'horas_estimadas': round(total_h_est, 2),
            'horas_reales': round(total_h_real, 2),
            'diferencia_horas': round(total_h_real - total_h_est, 2),
            'eficiencia_pct': eficiencia,
            'cantidad_total': round(total_cant, 1),
            'rendimiento_real': rend_real,
            'unidad': unidad,
            'tareas_completadas': tareas_count,
            'semaforo': _semaforo(eficiencia),
        })

    ranking.sort(key=lambda x: x['eficiencia_pct'], reverse=True)
    return ranking
