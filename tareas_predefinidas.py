# Tareas predefinidas por etapa de construcción
# Basado en la imagen proporcionada por el usuario

TAREAS_POR_ETAPA = {
    'Excavación': [
        'Replanteo y marcado del terreno',
        'Excavación para fundaciones',
        'Excavación para instalaciones subterráneas',
        'Nivelación y compactación del terreno',
        'Retiro de material excavado',
        'Verificación de niveles según planos',
        'Preparación de base para fundaciones'
    ],
    
    'Fundaciones': [
        'Armado de hierros para fundaciones',
        'Colocación de hormigón en fundaciones',
        'Construcción de bases y zapatas',
        'Impermeabilización de fundaciones',
        'Construcción de muros de contención',
        'Verificación de niveles y plomadas',
        'Curado del hormigón'
    ],
    
    'Estructura': [
        'Armado de columnas',
        'Hormigonado de columnas',
        'Armado de vigas',
        'Hormigonado de vigas',
        'Armado de losas',
        'Hormigonado de losas',
        'Construcción de escaleras',
        'Verificación estructural'
    ],
    
    'Mampostería': [
        'Construcción de muros exteriores',
        'Construcción de muros interiores',
        'Construcción de tabiques divisorios',
        'Colocación de dinteles',
        'Verificación de aplomes y niveles',
        'Construcción de antepechos',
        'Preparación para instalaciones'
    ],
    
    'Techos': [
        'Construcción de estructura de techo',
        'Colocación de aislación térmica',
        'Impermeabilización de cubierta',
        'Colocación de tejas o chapa',
        'Instalación de canaletas',
        'Construcción de aleros',
        'Sellado de juntas y uniones'
    ],
    
    'Instalaciones Eléctricas': [
        'Canalización eléctrica',
        'Cableado principal',
        'Instalación de tablero eléctrico',
        'Colocación de tomas y llaves',
        'Instalación de luminarias',
        'Conexión de electrodomésticos',
        'Pruebas y puesta en marcha'
    ],
    
    'Instalaciones Sanitarias': [
        'Instalación de cañerías de agua',
        'Instalación de desagües',
        'Colocación de artefactos sanitarios',
        'Instalación de grifería',
        'Conexión a red cloacal',
        'Pruebas hidráulicas',
        'Sellado e impermeabilización'
    ],
    
    'Instalaciones de Gas': [
        'Tendido de cañería de gas',
        'Instalación de medidor',
        'Conexión de artefactos',
        'Pruebas de hermeticidad',
        'Habilitación con empresa gasífera',
        'Señalización de seguridad',
        'Verificación de ventilaciones'
    ],
    
    'Revoque Grueso': [
        'Preparación de superficies',
        'Aplicación de revoque grueso exterior',
        'Aplicación de revoque grueso interior',
        'Verificación de verticalidad',
        'Corrección de imperfecciones',
        'Preparación para revoque fino',
        'Curado del revoque'
    ],
    
    'Revoque Fino': [
        'Preparación de mezcla fina',
        'Aplicación de revoque fino interior',
        'Aplicación de revoque fino exterior',
        'Alisado y terminación',
        'Corrección de detalles',
        'Preparación para pintura',
        'Limpieza de superficies'
    ],
    
    'Pisos': [
        'Preparación de contrapisos',
        'Nivelación de superficies',
        'Colocación de pisos cerámicos',
        'Colocación de pisos de madera',
        'Instalación de zócalos',
        'Sellado de juntas',
        'Limpieza final de pisos'
    ],
    
    'Carpintería': [
        'Instalación de marcos de puertas',
        'Instalación de marcos de ventanas',
        'Colocación de hojas de puertas',
        'Colocación de hojas de ventanas',
        'Instalación de herrajes',
        'Ajuste y regulación',
        'Sellado perimetral'
    ],
    
    'Pintura': [
        'Preparación de superficies',
        'Aplicación de imprimación',
        'Lijado entre manos',
        'Aplicación de pintura interior',
        'Aplicación de pintura exterior',
        'Retoques y detalles',
        'Limpieza de elementos'
    ],
    
    'Instalaciones Complementarias': [
        'Instalación de aire acondicionado',
        'Instalación de calefacción',
        'Instalación de sistema de seguridad',
        'Instalación de portones automáticos',
        'Colocación de toldos',
        'Instalación de sistema de riego',
        'Configuración domótica'
    ],
    
    'Limpieza Final': [
        'Limpieza de obra gruesa',
        'Limpieza de vidrios',
        'Limpieza de pisos y superficies',
        'Retiro de material sobrante',
        'Limpieza de instalaciones',
        'Entrega de documentación',
        'Inspección final'
    ]
}

def obtener_tareas_por_etapa(nombre_etapa):
    """Obtiene las tareas predefinidas para una etapa específica"""
    return TAREAS_POR_ETAPA.get(nombre_etapa, [])

def obtener_todas_las_etapas_con_tareas():
    """Retorna todas las etapas con sus tareas asociadas"""
    return TAREAS_POR_ETAPA