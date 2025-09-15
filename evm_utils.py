"""
Earned Value Management (EVM) utilities for OBYRA
Implements S-curve analysis, planning distribution, and performance monitoring
"""

from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import func
from app import db


def lunes_iso(d: date) -> date:
    """Convert a date to the Monday of its ISO week"""
    return d - timedelta(days=d.weekday())  # 0=Monday


def semanas_entre(inicio: date, fin: date):
    """Generate list of Monday dates between start and end dates"""
    if not inicio or not fin:
        return []
    
    s = lunes_iso(inicio)
    e = lunes_iso(fin)
    weeks = []
    while s <= e:
        weeks.append(s)
        s += timedelta(days=7)
    return weeks


def generar_plan_lineal(tarea_id):
    """Generate linear weekly distribution for a task"""
    from models import TareaEtapa, TareaPlanSemanal
    
    tarea = TareaEtapa.query.get(tarea_id)
    if not tarea or not tarea.fecha_inicio or not tarea.fecha_fin:
        return False
    
    # Validate dates
    if tarea.fecha_fin < tarea.fecha_inicio:
        return False
    
    # Calculate weeks and distribution
    weeks = semanas_entre(tarea.fecha_inicio, tarea.fecha_fin)
    if not weeks:
        return False
        
    n = max(len(weeks), 1)
    qty_per_week = float(tarea.cantidad_objetivo or 0) / n
    pv_per_week = float(tarea.presupuesto_mo or 0) / n
    
    # Clear existing planning
    TareaPlanSemanal.query.filter_by(tarea_id=tarea_id).delete()
    
    # Create new weekly planning records
    for semana in weeks:
        plan = TareaPlanSemanal(
            tarea_id=tarea_id,
            semana=semana,
            qty_plan=qty_per_week,
            pv_mo=pv_per_week
        )
        db.session.add(plan)
    
    try:
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error generating linear plan: {e}")
        return False


def recalcular_avance_semanal(tarea_id):
    """Recalculate weekly progress aggregation from approved advances"""
    from models import TareaEtapa, TareaAvance, TareaAvanceSemanal
    
    tarea = TareaEtapa.query.get(tarea_id)
    if not tarea:
        return False
    
    # Clear existing weekly aggregation
    TareaAvanceSemanal.query.filter_by(tarea_id=tarea_id).delete()
    
    # Get approved advances (DB-agnostic approach)
    approved_advances = (TareaAvance.query
        .filter(
            TareaAvance.tarea_id == tarea_id,
            TareaAvance.estado == 'aprobado',
            TareaAvance.approved_at.isnot(None)
        )
        .all())
    
    # Group by week in Python (DB-agnostic)
    weekly_data = {}
    for avance in approved_advances:
        # Convert to Monday of the week
        semana = lunes_iso(avance.approved_at.date())
        
        if semana not in weekly_data:
            weekly_data[semana] = {
                'qty_real': 0,
                'total_horas': 0
            }
        
        weekly_data[semana]['qty_real'] += float(avance.cantidad_ingresada or 0)
        weekly_data[semana]['total_horas'] += float(avance.horas_trabajadas or 0)
    
    # Create weekly aggregation records
    for semana, data in weekly_data.items():
        # Calculate actual cost (AC) based on hours worked
        # TODO: Integrate with real hourly rates from user profiles
        ac_mo = data['total_horas'] * 25.0  # Base rate $25/hour
        
        avance_sem = TareaAvanceSemanal(
            tarea_id=tarea_id,
            semana=semana,
            qty_real=data['qty_real'],
            ac_mo=ac_mo,
            ev_mo=0  # Will be calculated in curva_s_tarea function
        )
        db.session.add(avance_sem)
    
    try:
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error recalculating weekly progress: {e}")
        return False


def curva_s_tarea(tarea_id, desde=None, hasta=None):
    """Calculate S-curve data (PV, EV, AC) for a task"""
    from models import TareaEtapa, TareaPlanSemanal, TareaAvanceSemanal
    
    tarea = TareaEtapa.query.get(tarea_id)
    if not tarea:
        return []
    
    # Get planning and actual data
    plan_data = {r.semana: r for r in TareaPlanSemanal.query.filter_by(tarea_id=tarea_id).all()}
    real_data = {r.semana: r for r in TareaAvanceSemanal.query.filter_by(tarea_id=tarea_id).all()}
    
    # Get all weeks (union of planned and actual weeks)
    all_weeks = sorted(set(plan_data.keys()) | set(real_data.keys()))
    
    if desde:
        all_weeks = [w for w in all_weeks if w >= desde]
    if hasta:
        all_weeks = [w for w in all_weeks if w <= hasta]
    
    if not all_weeks:
        return []
    
    # Calculate full task totals (not filtered by date range)
    qty_plan_total = sum((plan.qty_plan for plan in TareaPlanSemanal.query.filter_by(tarea_id=tarea_id).all())) or 1
    presup_total = float(tarea.presupuesto_mo or 0)
    
    # Calculate cumulative values
    pv_acum = ev_acum = ac_acum = qty_real_acum = 0
    results = []
    
    for semana in all_weeks:
        # Planned Value (PV) this week
        pv_semana = plan_data[semana].pv_mo if semana in plan_data else 0
        pv_acum += float(pv_semana)
        
        # Actual quantities and costs this week
        if semana in real_data:
            qty_real_semana = real_data[semana].qty_real
            ac_semana = real_data[semana].ac_mo
        else:
            qty_real_semana = 0
            ac_semana = 0
        
        qty_real_acum += float(qty_real_semana)
        ac_acum += float(ac_semana)
        
        # Earned Value (EV) calculation - based on actual quantity completed
        ev_acum = presup_total * (qty_real_acum / qty_plan_total)
        
        # Performance indicators
        cpi = (ev_acum / ac_acum) if ac_acum > 0 else None
        spi = (ev_acum / pv_acum) if pv_acum > 0 else None
        
        results.append({
            'semana': semana.isoformat(),
            'pv': round(pv_acum, 2),
            'ev': round(ev_acum, 2),
            'ac': round(ac_acum, 2),
            'cpi': round(cpi, 3) if cpi else None,
            'spi': round(spi, 3) if spi else None,
            'qty_plan_acum': round(sum((plan_data[w].qty_plan if w in plan_data else 0) for w in all_weeks if w <= semana), 2),
            'qty_real_acum': round(qty_real_acum, 2)
        })
    
    return results


def detectar_alertas_evm(obra_id=None, etapa_id=None, tarea_id=None):
    """Detect EVM performance alerts (CPI < 0.9, SPI < 0.9, overdue tasks)"""
    from models import TareaEtapa, EtapaObra, Obra
    
    alerts = []
    
    if tarea_id:
        # Single task analysis
        tareas = [TareaEtapa.query.get(tarea_id)]
    elif etapa_id:
        # All tasks in stage
        etapa = EtapaObra.query.get(etapa_id)
        tareas = etapa.tareas if etapa else []
    elif obra_id:
        # All tasks in project
        obra = Obra.query.get(obra_id)
        tareas = []
        if obra:
            for etapa in obra.etapas:
                tareas.extend(etapa.tareas)
    else:
        # All tasks with EVM data
        tareas = TareaEtapa.query.filter(
            TareaEtapa.fecha_inicio.isnot(None),
            TareaEtapa.fecha_fin.isnot(None),
            TareaEtapa.presupuesto_mo.isnot(None)
        ).all()
    
    today = date.today()
    
    for tarea in tareas:
        if not tarea or not tarea.fecha_inicio or not tarea.fecha_fin:
            continue
            
        # Get latest S-curve data
        curve_data = curva_s_tarea(tarea.id)
        if not curve_data:
            continue
            
        latest_week = curve_data[-1]
        
        # Check for performance issues
        if latest_week['cpi'] and latest_week['cpi'] < 0.9:
            alerts.append({
                'type': 'cost_performance',
                'severity': 'high' if latest_week['cpi'] < 0.8 else 'medium',
                'tarea_id': tarea.id,
                'tarea_nombre': tarea.nombre,
                'message': f"CPI bajo: {latest_week['cpi']:.2f} (sobrecosto)",
                'cpi': latest_week['cpi'],
                'fecha': today
            })
        
        if latest_week['spi'] and latest_week['spi'] < 0.9:
            alerts.append({
                'type': 'schedule_performance', 
                'severity': 'high' if latest_week['spi'] < 0.8 else 'medium',
                'tarea_id': tarea.id,
                'tarea_nombre': tarea.nombre,
                'message': f"SPI bajo: {latest_week['spi']:.2f} (atraso cronograma)",
                'spi': latest_week['spi'],
                'fecha': today
            })
        
        # Check for overdue tasks
        if today > tarea.fecha_fin and tarea.pct_completado < 100:
            alerts.append({
                'type': 'overdue_task',
                'severity': 'high',
                'tarea_id': tarea.id,
                'tarea_nombre': tarea.nombre,
                'message': f"Tarea vencida: {(today - tarea.fecha_fin).days} días de retraso",
                'days_overdue': (today - tarea.fecha_fin).days,
                'fecha': today
            })
    
    return alerts


def curva_s_etapa(etapa_id, desde=None, hasta=None):
    """Calculate aggregated S-curve for all tasks in a stage"""
    from models import EtapaObra
    
    etapa = EtapaObra.query.get(etapa_id)
    if not etapa:
        return []
    
    # Aggregate all task curves
    all_weeks = set()
    task_curves = {}
    
    for tarea in etapa.tareas:
        if not tarea.fecha_inicio or not tarea.fecha_fin or not tarea.presupuesto_mo:
            continue
            
        curve = curva_s_tarea(tarea.id, desde, hasta)
        if curve:
            task_curves[tarea.id] = {item['semana']: item for item in curve}
            all_weeks.update(item['semana'] for item in curve)
    
    if not all_weeks:
        return []
    
    # Aggregate by week
    all_weeks = sorted(all_weeks)
    results = []
    
    for semana in all_weeks:
        pv_total = ev_total = ac_total = 0
        
        for tarea_id, curve_data in task_curves.items():
            if semana in curve_data:
                pv_total += curve_data[semana]['pv']
                ev_total += curve_data[semana]['ev']
                ac_total += curve_data[semana]['ac']
        
        # Calculate aggregated performance indicators
        cpi = (ev_total / ac_total) if ac_total > 0 else None
        spi = (ev_total / pv_total) if pv_total > 0 else None
        
        results.append({
            'semana': semana,
            'pv': round(pv_total, 2),
            'ev': round(ev_total, 2),
            'ac': round(ac_total, 2),
            'cpi': round(cpi, 3) if cpi else None,
            'spi': round(spi, 3) if spi else None
        })
    
    return results


def curva_s_obra(obra_id, desde=None, hasta=None):
    """Calculate aggregated S-curve for all tasks in a project"""
    from models import Obra
    
    obra = Obra.query.get(obra_id)
    if not obra:
        return []
    
    # Aggregate all stage curves
    all_weeks = set()
    stage_curves = {}
    
    for etapa in obra.etapas:
        curve = curva_s_etapa(etapa.id, desde, hasta)
        if curve:
            stage_curves[etapa.id] = {item['semana']: item for item in curve}
            all_weeks.update(item['semana'] for item in curve)
    
    if not all_weeks:
        return []
    
    # Aggregate by week
    all_weeks = sorted(all_weeks)
    results = []
    
    for semana in all_weeks:
        pv_total = ev_total = ac_total = 0
        
        for etapa_id, curve_data in stage_curves.items():
            if semana in curve_data:
                pv_total += curve_data[semana]['pv']
                ev_total += curve_data[semana]['ev']
                ac_total += curve_data[semana]['ac']
        
        # Calculate aggregated performance indicators
        cpi = (ev_total / ac_total) if ac_total > 0 else None
        spi = (ev_total / pv_total) if pv_total > 0 else None
        
        results.append({
            'semana': semana,
            'pv': round(pv_total, 2),
            'ev': round(ev_total, 2),
            'ac': round(ac_total, 2),
            'cpi': round(cpi, 3) if cpi else None,
            'spi': round(spi, 3) if spi else None
        })
    
    return results