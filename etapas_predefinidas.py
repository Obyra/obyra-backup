"""
Etapas predefinidas para proyectos de construcción - OBYRA IA
"""

ETAPAS_CONSTRUCCION = [
    # --- Etapas iniciales (antes de excavación) ---
    {"id": 16, "slug": "preliminares-obrador", "nombre": "Preliminares y Obrador", "descripcion": "Permisos, obrador y replanteo general", "orden": 5},
    {"id": 17, "slug": "demoliciones", "nombre": "Demoliciones", "descripcion": "Demolición de estructuras existentes", "orden": 6},
    {"id": 18, "slug": "movimiento-de-suelos", "nombre": "Movimiento de Suelos", "descripcion": "Excavación masiva, rellenos y compactación", "orden": 7},
    {"id": 19, "slug": "apuntalamientos", "nombre": "Apuntalamientos", "descripcion": "Sostenimiento provisorio de estructuras", "orden": 8},
    {"id": 20, "slug": "depresion-de-napa", "nombre": "Depresión de Napa / Bombeo", "descripcion": "Control de nivel freático y achique", "orden": 9},
    # --- Etapas existentes ---
    {"id": 1, "slug": "excavacion", "nombre": "Excavación", "descripcion": "Movimiento de suelos y preparación del terreno", "orden": 10},
    {"id": 2, "slug": "fundaciones", "nombre": "Fundaciones", "descripcion": "Cimientos y estructuras de base", "orden": 20},
    {"id": 3, "slug": "estructura", "nombre": "Estructura", "descripcion": "Hormigón / acero", "orden": 30},
    {"id": 4, "slug": "mamposteria", "nombre": "Mampostería", "descripcion": "Muros y paredes", "orden": 40},
    {"id": 21, "slug": "construccion-en-seco", "nombre": "Construcción en Seco", "descripcion": "Steel/wood frame, placas de yeso (Durlock)", "orden": 42},
    {"id": 5, "slug": "techos", "nombre": "Techos", "descripcion": "Cubiertas e impermeabilización", "orden": 50},
    {"id": 6, "slug": "instalaciones-electricas", "nombre": "Instalaciones Eléctricas", "descripcion": "Sistema eléctrico", "orden": 60},
    {"id": 7, "slug": "instalaciones-sanitarias", "nombre": "Instalaciones Sanitarias", "descripcion": "Agua y desagües", "orden": 70},
    {"id": 8, "slug": "instalaciones-gas", "nombre": "Instalaciones de Gas", "descripcion": "Sistema de gas natural", "orden": 80},
    {"id": 22, "slug": "ventilaciones-conductos", "nombre": "Ventilaciones y Conductos", "descripcion": "Conductos de ventilación, extracción y tiro", "orden": 82},
    {"id": 23, "slug": "impermeabilizaciones-aislaciones", "nombre": "Impermeabilizaciones y Aislaciones", "descripcion": "Membranas, hidrófugos, aislación térmica y acústica", "orden": 85},
    {"id": 9, "slug": "revoque-grueso", "nombre": "Revoque Grueso", "descripcion": "Base en paredes", "orden": 90},
    {"id": 24, "slug": "cielorrasos", "nombre": "Cielorrasos", "descripcion": "Cielorrasos aplicados, suspendidos y desmontables", "orden": 95},
    {"id": 25, "slug": "yeseria-enlucidos", "nombre": "Yesería y Enlucidos", "descripcion": "Enlucido de yeso, estucados y molduras", "orden": 98},
    {"id": 10, "slug": "revoque-fino", "nombre": "Revoque Fino", "descripcion": "Terminación", "orden": 100},
    {"id": 26, "slug": "contrapisos-carpetas", "nombre": "Contrapisos y Carpetas", "descripcion": "Contrapisos, carpetas de nivelación y pendientes", "orden": 105},
    {"id": 11, "slug": "pisos", "nombre": "Pisos", "descripcion": "Colocación y revestimientos", "orden": 110},
    {"id": 27, "slug": "revestimientos", "nombre": "Revestimientos", "descripcion": "Cerámicos, porcellanato, piedra y terminaciones", "orden": 112},
    {"id": 12, "slug": "carpinteria", "nombre": "Carpintería", "descripcion": "Puertas, ventanas, muebles", "orden": 120},
    {"id": 13, "slug": "pintura", "nombre": "Pintura", "descripcion": "Interior y exterior", "orden": 130},
    {"id": 28, "slug": "provisiones-colocaciones", "nombre": "Provisiones y Colocaciones", "descripcion": "Griferías, sanitarios, accesorios y terminaciones", "orden": 135},
    {"id": 14, "slug": "instalaciones-complementarias", "nombre": "Instalaciones Complementarias", "descripcion": "A/A, calefacción, etc.", "orden": 140},
    {"id": 15, "slug": "limpieza-final", "nombre": "Limpieza Final", "descripcion": "Acondicionamiento final", "orden": 150},
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
    from app import db
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
                estado='pendiente'
            )
            
            db.session.add(nueva_etapa)
            etapas_creadas.append(nueva_etapa)
    
    db.session.commit()
    return etapas_creadas

def crear_etapas_desde_catalogo(obra_id, catalogo_ids):
    """Crea etapas en la obra basadas en IDs del catálogo (idempotente)"""
    from app import db
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
                estado='pendiente'
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