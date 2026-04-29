"""
Etapas predefinidas para proyectos de construcción - OBYRA IA
"""

ETAPAS_CONSTRUCCION = [
    # Nivel 1 – Inicio
    {"id": 16, "slug": "preliminares-obrador", "nombre": "Preliminares y Obrador", "descripcion": "Permisos, obrador y replanteo general", "orden": 5, "nivel": 1},
    # Nivel 2
    {"id": 17, "slug": "demoliciones", "nombre": "Demoliciones", "descripcion": "Demolición de estructuras existentes", "orden": 6, "nivel": 2},
    # Nivel 3 – Paralelas
    {"id": 18, "slug": "movimiento-de-suelos", "nombre": "Movimiento de Suelos", "descripcion": "Excavación masiva, rellenos y compactación", "orden": 7, "nivel": 3},
    {"id": 1, "slug": "excavacion", "nombre": "Excavación", "descripcion": "Movimiento de suelos y preparación del terreno", "orden": 10, "nivel": 3},
    # Nivel 4 – Opcionales
    {"id": 19, "slug": "apuntalamientos", "nombre": "Apuntalamientos", "descripcion": "Sostenimiento provisorio de estructuras", "orden": 8, "nivel": 4, "es_opcional": True},
    {"id": 20, "slug": "depresion-de-napa", "nombre": "Depresión de Napa / Bombeo", "descripcion": "Control de nivel freático y achique", "orden": 9, "nivel": 4, "es_opcional": True},
    # Nivel 5
    {"id": 2, "slug": "fundaciones", "nombre": "Fundaciones", "descripcion": "Cimientos y estructuras de base", "orden": 20, "nivel": 5},
    # Nivel 6
    {"id": 3, "slug": "estructura", "nombre": "Estructura", "descripcion": "Hormigón / acero", "orden": 30, "nivel": 6},
    # Nivel 7
    {"id": 4, "slug": "mamposteria", "nombre": "Mampostería", "descripcion": "Muros y paredes", "orden": 40, "nivel": 7},
    # Nivel 8 – Paralelas
    {"id": 5, "slug": "techos", "nombre": "Techos", "descripcion": "Cubiertas e impermeabilización", "orden": 50, "nivel": 8},
    {"id": 23, "slug": "impermeabilizaciones-aislaciones", "nombre": "Impermeabilizaciones y Aislaciones", "descripcion": "Membranas, hidrófugos, aislación térmica y acústica", "orden": 85, "nivel": 8},
    # Nivel 9 – Instalaciones (paralelas)
    {"id": 6, "slug": "instalaciones-electricas", "nombre": "Instalaciones Eléctricas", "descripcion": "Sistema eléctrico", "orden": 60, "nivel": 9},
    {"id": 7, "slug": "instalaciones-sanitarias", "nombre": "Instalaciones Sanitarias y Provisiones", "descripcion": "Agua, desagües, griferías, sanitarios y accesorios", "orden": 70, "nivel": 9},
    {"id": 8, "slug": "instalaciones-gas", "nombre": "Instalaciones de Gas", "descripcion": "Sistema de gas natural", "orden": 80, "nivel": 9},
    {"id": 22, "slug": "ventilaciones-conductos", "nombre": "Ventilaciones y Conductos", "descripcion": "Conductos de ventilación, extracción y tiro", "orden": 82, "nivel": 9},
    # Nivel 10
    {"id": 9, "slug": "revoque-grueso", "nombre": "Revoque Grueso", "descripcion": "Base en paredes", "orden": 90, "nivel": 10},
    # Nivel 11 – Paralelas
    {"id": 26, "slug": "contrapisos-carpetas", "nombre": "Contrapisos y Carpetas", "descripcion": "Contrapisos, carpetas de nivelación y pendientes", "orden": 105, "nivel": 11},
    {"id": 24, "slug": "cielorrasos", "nombre": "Cielorrasos", "descripcion": "Cielorrasos aplicados, suspendidos y desmontables", "orden": 95, "nivel": 11},
    # Nivel 12 – Paralelas
    {"id": 10, "slug": "revoque-fino", "nombre": "Revoque Fino", "descripcion": "Terminación", "orden": 100, "nivel": 12},
    {"id": 25, "slug": "yeseria-enlucidos", "nombre": "Yesería y Enlucidos", "descripcion": "Enlucido de yeso, estucados y molduras", "orden": 98, "nivel": 12},
    # Nivel 13
    {"id": 11, "slug": "pisos", "nombre": "Pisos y Revestimientos", "descripcion": "Cerámicos, porcellanato, piedra y terminaciones de piso y pared", "orden": 110, "nivel": 13},
    # Nivel 14
    {"id": 21, "slug": "construccion-en-seco", "nombre": "Construcción en Seco", "descripcion": "Steel/wood frame, placas de yeso (Durlock)", "orden": 42, "nivel": 14},
    # Nivel 15
    {"id": 12, "slug": "carpinteria", "nombre": "Carpintería", "descripcion": "Puertas, ventanas, muebles", "orden": 120, "nivel": 15},
    # Nivel 16
    {"id": 13, "slug": "pintura", "nombre": "Pintura", "descripcion": "Interior y exterior", "orden": 130, "nivel": 16},
    # Nivel 17
    {"id": 14, "slug": "instalaciones-complementarias", "nombre": "Instalaciones Complementarias", "descripcion": "A/A, calefacción, etc.", "orden": 140, "nivel": 17},
    # Nivel 18
    {"id": 15, "slug": "limpieza-final", "nombre": "Limpieza Final", "descripcion": "Acondicionamiento final", "orden": 150, "nivel": 18},
    # ============================================================
    # Etapas específicas de Remodelación / Refacción
    # Solo aplican cuando naturaleza_proyecto = 'remodelacion'.
    # IDs altos (27+) para no chocar con catálogo histórico.
    # ============================================================
    {"id": 27, "slug": "retiro-revestimientos", "nombre": "Retiro de Revestimientos", "descripcion": "Retiro de pisos, azulejos y revestimientos existentes", "orden": 7, "nivel": 2},
    {"id": 28, "slug": "retiro-instalaciones", "nombre": "Retiro de Instalaciones Existentes", "descripcion": "Desmonte de cañerías, cables y artefactos a reemplazar", "orden": 8, "nivel": 2},
    {"id": 29, "slug": "refuerzo-estructural", "nombre": "Refuerzo Estructural", "descripcion": "Vigas, columnas y refuerzos en estructura existente", "orden": 35, "nivel": 6, "es_opcional": True},
    {"id": 30, "slug": "tratamiento-humedad", "nombre": "Tratamiento de Humedad", "descripcion": "Diagnóstico y reparación de humedad en muros existentes", "orden": 88, "nivel": 8, "es_opcional": True},
    {"id": 31, "slug": "renovacion-aberturas", "nombre": "Renovación de Aberturas", "descripcion": "Reemplazo de puertas y ventanas existentes", "orden": 122, "nivel": 15, "es_opcional": True},
]

def obtener_etapas_disponibles():
    """Retorna lista de etapas predefinidas"""
    return ETAPAS_CONSTRUCCION

def obtener_etapa_por_id(catalog_id):
    """Retorna etapa del catalogo por ID"""
    return next((e for e in ETAPAS_CONSTRUCCION if e['id'] == catalog_id), None)

def obtener_etapa_por_slug(slug):
    """Retorna etapa del catalogo por slug"""
    return next((e for e in ETAPAS_CONSTRUCCION if e['slug'] == slug), None)

def crear_etapas_para_obra(obra_id, etapas_seleccionadas):
    """Crea las etapas seleccionadas para una obra específica"""
    from extensions import db
    from models import EtapaObra

    etapas_creadas = []
    
    for etapa_nombre in etapas_seleccionadas:
        # Buscar la etapa predefinida
        etapa_predefinida = next((e for e in ETAPAS_CONSTRUCCION if e['nombre'] == etapa_nombre), None)
        
        if etapa_predefinida:
            nueva_etapa = EtapaObra(
                obra_id=obra_id,
                nombre=etapa_predefinida['nombre'],
                descripcion=etapa_predefinida['descripcion'],
                orden=etapa_predefinida['orden'],
                estado='pendiente',
                nivel_encadenamiento=etapa_predefinida.get('nivel'),
                es_opcional=etapa_predefinida.get('es_opcional', False),
            )
            
            db.session.add(nueva_etapa)
            etapas_creadas.append(nueva_etapa)
    
    db.session.commit()
    return etapas_creadas

def crear_etapas_desde_catalogo(obra_id, catalogo_ids):
    """Crea etapas en la obra basadas en IDs del catálogo (idempotente)"""
    from extensions import db
    from models import EtapaObra

    creadas = []
    existentes = []
    
    for catalog_id in catalogo_ids:
        etapa_catalogo = obtener_etapa_por_id(catalog_id)
        if not etapa_catalogo:
            continue
            
        # Verificar si ya existe por slug o nombre
        from sqlalchemy import or_
        etapa_existente = EtapaObra.query.filter(
            EtapaObra.obra_id == obra_id
        ).filter(
            or_(
                EtapaObra.nombre == etapa_catalogo['nombre'],
                # Comparación flexible de slug si ya hay etapas con slug-like names
                EtapaObra.nombre.ilike(f"%{etapa_catalogo['slug'].replace('-', '%')}%")
            )
        ).first()
        
        if etapa_existente:
            existentes.append({
                'id': etapa_existente.id,
                'slug': etapa_catalogo['slug'],
                'nombre': etapa_existente.nombre
            })
        else:
            nueva_etapa = EtapaObra(
                obra_id=obra_id,
                nombre=etapa_catalogo['nombre'],
                descripcion=etapa_catalogo['descripcion'],
                orden=etapa_catalogo['orden'],
                estado='pendiente',
                nivel_encadenamiento=etapa_catalogo.get('nivel'),
                es_opcional=etapa_catalogo.get('es_opcional', False),
            )
            
            db.session.add(nueva_etapa)
            db.session.flush()  # Para obtener el ID
            
            creadas.append({
                'id': nueva_etapa.id,
                'slug': etapa_catalogo['slug'],
                'nombre': nueva_etapa.nombre
            })
    
    # Don't commit here - let the caller handle the transaction
    db.session.flush()  # Ensure IDs are available for task creation
    return creadas, existentes