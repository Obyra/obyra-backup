"""
Servicio de dependencias entre etapas de obra.
Gestiona niveles de encadenamiento, dependencias explícitas
y cascadeo automático de fechas.
"""
from datetime import timedelta
from extensions import db
from models.projects import EtapaObra, EtapaDependencia


# ---------------------------------------------------------------------------
# Catálogo nombre → nivel  (para matcheo flexible)
# ---------------------------------------------------------------------------
_NIVEL_POR_NOMBRE = None


def _get_nivel_map():
    """Lazy-load del catálogo para evitar imports circulares."""
    global _NIVEL_POR_NOMBRE
    if _NIVEL_POR_NOMBRE is None:
        from etapas_predefinidas import ETAPAS_CONSTRUCCION
        _NIVEL_POR_NOMBRE = {}
        for e in ETAPAS_CONSTRUCCION:
            _NIVEL_POR_NOMBRE[e['nombre'].lower().strip()] = {
                'nivel': e.get('nivel'),
                'es_opcional': e.get('es_opcional', False),
            }
    return _NIVEL_POR_NOMBRE


# ---------------------------------------------------------------------------
# Asignar niveles por defecto
# ---------------------------------------------------------------------------
def asignar_niveles_por_defecto(obra_id):
    """Matchea etapas de la obra contra el catálogo y asigna nivel_encadenamiento.
    Solo toca etapas que aún no tienen nivel asignado.
    """
    etapas = EtapaObra.query.filter_by(obra_id=obra_id).all()
    mapa = _get_nivel_map()
    asignadas = 0

    for etapa in etapas:
        if etapa.nivel_encadenamiento is not None:
            continue  # ya tiene nivel

        key = etapa.nombre.lower().strip()
        info = mapa.get(key)
        if info and info['nivel'] is not None:
            etapa.nivel_encadenamiento = info['nivel']
            etapa.es_opcional = info['es_opcional']
            asignadas += 1

    if asignadas:
        db.session.flush()

    return asignadas


# ---------------------------------------------------------------------------
# Generar dependencias desde niveles
# ---------------------------------------------------------------------------
def generar_dependencias_desde_niveles(obra_id):
    """Crea dependencias explícitas en etapa_dependencias basadas en
    nivel_encadenamiento. Nivel N depende de todas las no-opcionales de nivel N-1.
    No duplica dependencias existentes.
    """
    etapas = (
        EtapaObra.query
        .filter_by(obra_id=obra_id)
        .filter(EtapaObra.nivel_encadenamiento.isnot(None))
        .order_by(EtapaObra.nivel_encadenamiento)
        .all()
    )

    if not etapas:
        return 0

    # Agrupar por nivel
    por_nivel = {}
    for e in etapas:
        por_nivel.setdefault(e.nivel_encadenamiento, []).append(e)

    niveles_ordenados = sorted(por_nivel.keys())

    # Dependencias existentes (para no duplicar)
    deps_existentes = set()
    deps = EtapaDependencia.query.filter(
        EtapaDependencia.etapa_id.in_([e.id for e in etapas])
    ).all()
    for d in deps:
        deps_existentes.add((d.etapa_id, d.depende_de_id))

    creadas = 0
    for i, nivel in enumerate(niveles_ordenados):
        if i == 0:
            continue  # primer nivel no tiene predecesoras

        nivel_anterior = niveles_ordenados[i - 1]
        predecesoras = [
            e for e in por_nivel[nivel_anterior]
            if not e.es_opcional
        ]

        if not predecesoras:
            # Si todas son opcionales, usar el nivel anterior no-opcional
            for j in range(i - 2, -1, -1):
                niv = niveles_ordenados[j]
                predecesoras = [e for e in por_nivel[niv] if not e.es_opcional]
                if predecesoras:
                    break

        for sucesora in por_nivel[nivel]:
            for pred in predecesoras:
                if (sucesora.id, pred.id) not in deps_existentes:
                    dep = EtapaDependencia(
                        etapa_id=sucesora.id,
                        depende_de_id=pred.id,
                        tipo='FS',
                        lag_dias=0,
                    )
                    db.session.add(dep)
                    deps_existentes.add((sucesora.id, pred.id))
                    creadas += 1

    if creadas:
        db.session.flush()

    return creadas


# ---------------------------------------------------------------------------
# Cascadeo de fechas (algoritmo principal)
# ---------------------------------------------------------------------------
def propagar_fechas_obra(obra_id, force_cascade=False):
    """Propaga fechas de etapas según dependencias y niveles.

    Algoritmo:
    1. Carga todas las etapas de la obra.
    2. Para cada etapa, determina sus predecesoras:
       - Dependencias explícitas (tabla etapa_dependencias)
       - O derivadas del nivel_encadenamiento
       - O fallback por orden secuencial
    3. Orden topológico (sin predecesoras primero).
    4. Para cada etapa en orden topo:
       - Skip si fechas_manuales == True (salvo que force_cascade y haya solapamiento)
       - Skip si estado == 'finalizada'
       - inicio_más_temprano = max(pred.fecha_fin + 1 + lag)
       - Si inicio_más_temprano > fecha_inicio → shift forward preservando duración

    Args:
        force_cascade: Si True, mueve etapas con fechas_manuales cuando hay
                       solapamiento (la predecesora termina después del inicio).
    """
    etapas = (
        EtapaObra.query
        .filter_by(obra_id=obra_id)
        .order_by(EtapaObra.orden)
        .all()
    )

    if not etapas:
        return []

    etapa_map = {e.id: e for e in etapas}

    # Construir grafo de dependencias
    deps = EtapaDependencia.query.filter(
        EtapaDependencia.etapa_id.in_([e.id for e in etapas])
    ).all()

    # predecesoras_map: etapa_id → [(pred_etapa_id, lag_dias), ...]
    predecesoras_map = {}
    for d in deps:
        predecesoras_map.setdefault(d.etapa_id, []).append(
            (d.depende_de_id, d.lag_dias)
        )

    # Para etapas sin dependencias explícitas y sin nivel, usar fallback secuencial
    etapas_con_deps = set(predecesoras_map.keys())
    etapas_con_nivel = {e.id for e in etapas if e.nivel_encadenamiento is not None}
    for i, e in enumerate(etapas):
        if e.id not in etapas_con_deps and e.id not in etapas_con_nivel and i > 0:
            # Fallback: depende de la etapa anterior por orden
            predecesoras_map.setdefault(e.id, []).append((etapas[i - 1].id, 0))

    # Orden topológico (Kahn's algorithm)
    in_degree = {e.id: 0 for e in etapas}
    sucesoras_graph = {e.id: [] for e in etapas}

    for etapa_id, preds in predecesoras_map.items():
        for pred_id, _ in preds:
            if pred_id in etapa_map:
                in_degree[etapa_id] = in_degree.get(etapa_id, 0) + 1
                sucesoras_graph.setdefault(pred_id, []).append(etapa_id)

    # Re-count in_degree properly
    in_degree = {e.id: 0 for e in etapas}
    for etapa_id, preds in predecesoras_map.items():
        for pred_id, _ in preds:
            if pred_id in etapa_map:
                in_degree[etapa_id] += 1

    cola = [eid for eid in in_degree if in_degree[eid] == 0]
    # Estabilizar orden por etapa.orden para resultados determinísticos
    cola.sort(key=lambda eid: etapa_map[eid].orden)
    orden_topo = []

    while cola:
        eid = cola.pop(0)
        orden_topo.append(eid)
        for suc_id in sucesoras_graph.get(eid, []):
            in_degree[suc_id] -= 1
            if in_degree[suc_id] == 0:
                cola.append(suc_id)
                cola.sort(key=lambda x: etapa_map[x].orden)

    # Si hay ciclos, agregar las que faltan al final
    restantes = [e.id for e in etapas if e.id not in set(orden_topo)]
    restantes.sort(key=lambda eid: etapa_map[eid].orden)
    orden_topo.extend(restantes)

    # Propagar fechas
    etapas_modificadas = []

    for eid in orden_topo:
        etapa = etapa_map[eid]

        if etapa.estado == 'finalizada':
            continue

        preds = predecesoras_map.get(eid, [])
        if not preds:
            continue

        # Calcular el inicio más temprano
        inicio_mas_temprano = None
        for pred_id, lag in preds:
            pred = etapa_map.get(pred_id)
            if not pred:
                continue

            # Usar fecha_fin_real si finalizada, sino fecha_fin_estimada
            fecha_fin_pred = None
            if pred.estado == 'finalizada' and pred.fecha_fin_real:
                fecha_fin_pred = pred.fecha_fin_real
            elif pred.fecha_fin_estimada:
                fecha_fin_pred = pred.fecha_fin_estimada
            else:
                continue

            candidata = fecha_fin_pred + timedelta(days=1 + lag)
            if inicio_mas_temprano is None or candidata > inicio_mas_temprano:
                inicio_mas_temprano = candidata

        if inicio_mas_temprano is None:
            continue

        # Si tiene fechas_manuales, solo mover si hay solapamiento real
        # (la predecesora termina después de cuando esta etapa empieza)
        if etapa.fechas_manuales and not force_cascade:
            continue
        if etapa.fechas_manuales and force_cascade:
            # Solo forzar si hay solapamiento (inicio actual < inicio requerido)
            if etapa.fecha_inicio_estimada and etapa.fecha_inicio_estimada >= inicio_mas_temprano:
                continue

        if etapa.fecha_inicio_estimada and inicio_mas_temprano != etapa.fecha_inicio_estimada:
            # Calcular duración actual para preservarla (mínimo 1 día)
            if etapa.fecha_inicio_estimada and etapa.fecha_fin_estimada:
                duracion = (etapa.fecha_fin_estimada - etapa.fecha_inicio_estimada).days
                if duracion < 1:
                    duracion = 14  # Default 14 días si la duración era inválida
            else:
                duracion = 14

            etapa.fecha_inicio_estimada = inicio_mas_temprano
            etapa.fecha_fin_estimada = inicio_mas_temprano + timedelta(days=duracion)
            etapas_modificadas.append(etapa)

        elif etapa.fecha_inicio_estimada is None:
            etapa.fecha_inicio_estimada = inicio_mas_temprano
            if etapa.fecha_fin_estimada is None:
                etapa.fecha_fin_estimada = inicio_mas_temprano + timedelta(days=14)
            etapas_modificadas.append(etapa)

    if etapas_modificadas:
        db.session.flush()

    return etapas_modificadas
