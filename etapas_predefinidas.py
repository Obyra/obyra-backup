"""
Etapas predefinidas para proyectos de construcción - OBYRA IA
"""

ETAPAS_CONSTRUCCION = [
    {
        'nombre': 'Excavación',
        'descripcion': 'Movimiento de suelos y preparación del terreno',
        'orden': 1
    },
    {
        'nombre': 'Fundaciones',
        'descripcion': 'Construcción de cimientos y estructuras de base',
        'orden': 2
    },
    {
        'nombre': 'Estructura',
        'descripcion': 'Construcción de estructura principal (hormigón, acero)',
        'orden': 3
    },
    {
        'nombre': 'Mampostería',
        'descripcion': 'Construcción de muros y paredes',
        'orden': 4
    },
    {
        'nombre': 'Techos',
        'descripcion': 'Construcción e impermeabilización de techos',
        'orden': 5
    },
    {
        'nombre': 'Instalaciones Eléctricas',
        'descripcion': 'Instalación del sistema eléctrico',
        'orden': 6
    },
    {
        'nombre': 'Instalaciones Sanitarias',
        'descripcion': 'Instalación de sistemas de agua y desagües',
        'orden': 7
    },
    {
        'nombre': 'Instalaciones de Gas',
        'descripcion': 'Instalación del sistema de gas natural',
        'orden': 8
    },
    {
        'nombre': 'Revoque Grueso',
        'descripcion': 'Aplicación de revoque base en paredes',
        'orden': 9
    },
    {
        'nombre': 'Revoque Fino',
        'descripcion': 'Aplicación de revoque terminación',
        'orden': 10
    },
    {
        'nombre': 'Pisos',
        'descripcion': 'Colocación de pisos y revestimientos',
        'orden': 11
    },
    {
        'nombre': 'Carpintería',
        'descripcion': 'Instalación de puertas, ventanas y muebles',
        'orden': 12
    },
    {
        'nombre': 'Pintura',
        'descripcion': 'Trabajos de pintura interior y exterior',
        'orden': 13
    },
    {
        'nombre': 'Instalaciones Complementarias',
        'descripcion': 'Aire acondicionado, calefacción, etc.',
        'orden': 14
    },
    {
        'nombre': 'Limpieza Final',
        'descripcion': 'Limpieza y acondicionamiento final',
        'orden': 15
    }
]

def obtener_etapas_disponibles():
    """Retorna lista de etapas predefinidas"""
    return ETAPAS_CONSTRUCCION

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