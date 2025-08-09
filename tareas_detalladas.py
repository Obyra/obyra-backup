"""
Tareas predefinidas por etapa de construcción con descripciones detalladas - OBYRA IA
FUENTE ÚNICA DE DATOS - Usar esta lista completa para auto-generar tareas
"""

# Tareas predefinidas por tipo de etapa con descripciones detalladas
TAREAS_DETALLADAS_POR_ETAPA = {
    'Excavación': [
        {
            'nombre': 'Replanteo y marcado del terreno',
            'descripcion': 'Marcar sobre el terreno las dimensiones y ubicación exacta de la construcción según planos'
        },
        {
            'nombre': 'Excavación para fundaciones',
            'descripcion': 'Excavación específica para las bases y fundaciones de la estructura'
        },
        {
            'nombre': 'Excavación para instalaciones subterráneas',
            'descripcion': 'Excavación de zanjas para cañerías de agua, cloacas y gas'
        },
        {
            'nombre': 'Nivelación y compactación del terreno',
            'descripcion': 'Nivelación y compactación del terreno según cotas del proyecto'
        },
        {
            'nombre': 'Retiro material excavado',
            'descripcion': 'Transporte y disposición del material excavado fuera de la obra'
        },
        {
            'nombre': 'Verificación de niveles según planos',
            'descripcion': 'Control topográfico y verificación de cotas según documentación técnica'
        },
        {
            'nombre': 'Preparación de base para fundaciones',
            'descripcion': 'Acondicionamiento del terreno para recibir las fundaciones'
        },
        {
            'nombre': 'Limpieza y preparación del sitio',
            'descripcion': 'Limpieza general del terreno y preparación para inicio de obra'
        },
        {
            'nombre': 'Instalación de cerco perimetral',
            'descripcion': 'Colocación de cerco de seguridad alrededor del perímetro de obra'
        },
        {
            'nombre': 'Instalación de servicios temporales',
            'descripcion': 'Conexión provisoria de agua, luz y otros servicios necesarios'
        },
        {
            'nombre': 'Estudio de suelos',
            'descripcion': 'Análisis del suelo para determinar características y capacidad portante'
        },
        {
            'nombre': 'Verificación de medianeras',
            'descripcion': 'Control y verificación de límites del terreno con propiedades lindantes'
        },
        {
            'nombre': 'Demolición de estructuras existentes',
            'descripcion': 'Demolición de construcciones existentes que interfieran con el proyecto'
        },
        {
            'nombre': 'Relleno y compactación de terreno',
            'descripcion': 'Relleno con material seleccionado y compactación según especificaciones'
        },
        {
            'nombre': 'Drenaje preliminar',
            'descripcion': 'Instalación de drenajes temporarios para manejo de aguas'
        }
    ],
    'Fundaciones': [
        {
            'nombre': 'Armado de hierros para fundaciones',
            'descripcion': 'Preparación y colocación de armaduras de acero según planos estructurales'
        },
        {
            'nombre': 'Colocación de hormigón en fundaciones',
            'descripcion': 'Vertido y vibrado del hormigón en fundaciones según especificaciones técnicas'
        },
        {
            'nombre': 'Construcción de bases y zapatas',
            'descripcion': 'Construcción de zapatas aisladas y bases para columnas'
        },
        {
            'nombre': 'Impermeabilización de fundaciones',
            'descripcion': 'Aplicación de membrana impermeabilizante en fundaciones'
        },
        {
            'nombre': 'Construcción de muros de contención',
            'descripcion': 'Construcción de muros para contención de tierras si es necesario'
        },
        {
            'nombre': 'Verificación de niveles y plomadas',
            'descripcion': 'Control de verticalidad y niveles de fundaciones terminadas'
        },
        {
            'nombre': 'Curado del hormigón',
            'descripcion': 'Mantenimiento de humedad para correcto fraguado del hormigón'
        },
        {
            'nombre': 'Excavación de zapatas',
            'descripcion': 'Excavación específica para zapatas individuales'
        },
        {
            'nombre': 'Colocación de piedra desplazadora',
            'descripcion': 'Colocación de piedra para reducir volumen de hormigón'
        },
        {
            'nombre': 'Armado de encadenados',
            'descripcion': 'Preparación de armaduras para vigas de encadenado'
        },
        {
            'nombre': 'Hormigonado de encadenados',
            'descripcion': 'Vertido de hormigón en vigas de encadenado perimetral'
        },
        {
            'nombre': 'Aislación hidrófuga horizontal',
            'descripcion': 'Colocación de barrera contra ascensión de humedad'
        },
        {
            'nombre': 'Relleno con material seleccionado',
            'descripcion': 'Relleno perimetral a fundaciones con material granular'
        },
        {
            'nombre': 'Compactación de rellenos',
            'descripcion': 'Compactación mecánica de rellenos perimetrales'
        }
    ],
    'Estructura': [
        {
            'nombre': 'Armado de columnas',
            'descripcion': 'Preparación y colocación de armaduras de acero para columnas estructurales'
        },
        {
            'nombre': 'Hormigonado de columnas',
            'descripcion': 'Vertido de hormigón en columnas con vibrado adecuado'
        },
        {
            'nombre': 'Armado de vigas',
            'descripcion': 'Colocación de armaduras de acero en vigas según planos estructurales'
        },
        {
            'nombre': 'Hormigonado de vigas',
            'descripcion': 'Vertido de hormigón en vigas con control de calidad y vibrado'
        },
        {
            'nombre': 'Armado de losas',
            'descripcion': 'Instalación de armaduras de acero en losas y entrepisos'
        },
        {
            'nombre': 'Hormigonado de losas',
            'descripcion': 'Vertido y nivelación de hormigón en losas con acabado superficial'
        },
        {
            'nombre': 'Construcción de escaleras',
            'descripcion': 'Construcción de escaleras principales y secundarias'
        },
        {
            'nombre': 'Verificación estructural',
            'descripcion': 'Control de calidad y verificación de elementos estructurales'
        },
        {
            'nombre': 'Colocación de encofrados',
            'descripcion': 'Instalación de moldes para elementos estructurales'
        },
        {
            'nombre': 'Desencofrado y limpieza',
            'descripcion': 'Retiro de encofrados y limpieza de superficies de hormigón'
        },
        {
            'nombre': 'Control de calidad del hormigón',
            'descripcion': 'Ensayos y verificación de resistencia del hormigón'
        },
        {
            'nombre': 'Apuntalamiento temporal',
            'descripcion': 'Instalación de puntales y sistemas de apeo temporarios'
        },
        {
            'nombre': 'Juntas de dilatación',
            'descripcion': 'Ejecución de juntas estructurales según proyecto'
        },
        {
            'nombre': 'Tratamiento de superficies',
            'descripcion': 'Preparación de superficies de hormigón visto'
        },
        {
            'nombre': 'Nivelación final de losas',
            'descripcion': 'Verificación y corrección de niveles finales en losas'
        }
    ],
    'Mampostería': [
        {
            'nombre': 'Construcción de muros exteriores',
            'descripcion': 'Construcción de muros perimetrales con ladrillos o bloques'
        },
        {
            'nombre': 'Construcción de muros interiores',
            'descripcion': 'Construcción de muros divisorios interiores'
        },
        {
            'nombre': 'Construcción de tabiques divisorios',
            'descripcion': 'Construcción de tabiques livianos para división de ambientes'
        },
        {
            'nombre': 'Colocación de dinteles',
            'descripcion': 'Instalación de dinteles sobre aberturas de puertas y ventanas'
        },
        {
            'nombre': 'Verificación de aplomes y niveles',
            'descripcion': 'Control de verticalidad y horizontalidad de muros'
        },
        {
            'nombre': 'Construcción de antepechos',
            'descripcion': 'Construcción de antepechos de ventanas'
        },
        {
            'nombre': 'Preparación para instalaciones',
            'descripcion': 'Ejecución de canaletas y perforaciones para instalaciones'
        }
    ],
    'Techos': [
        {
            'nombre': 'Construcción de estructura de techo',
            'descripcion': 'Construcción de estructura portante del techo con cabriadas y correas'
        },
        {
            'nombre': 'Colocación de aislación térmica',
            'descripcion': 'Instalación de materiales aislantes bajo cubierta'
        },
        {
            'nombre': 'Impermeabilización de cubierta',
            'descripcion': 'Aplicación de membrana impermeabilizante en cubierta'
        },
        {
            'nombre': 'Colocación de tejas o chapa',
            'descripcion': 'Instalación del material de cubierta final según proyecto'
        },
        {
            'nombre': 'Instalación de canaletas',
            'descripcion': 'Colocación de sistema de desagüe pluvial perimetral'
        },
        {
            'nombre': 'Construcción de aleros',
            'descripcion': 'Construcción de aleros y remates perimetrales'
        },
        {
            'nombre': 'Sellado de juntas y uniones',
            'descripcion': 'Sellado hermético de todas las uniones de cubierta'
        }
    ],
    'Instalaciones Eléctricas': [
        {
            'nombre': 'Canalización eléctrica',
            'descripcion': 'Instalación de caños y conductos para el paso de cables eléctricos'
        },
        {
            'nombre': 'Cableado principal',
            'descripcion': 'Tendido de cables desde tablero principal a circuitos secundarios'
        },
        {
            'nombre': 'Instalación de tablero eléctrico',
            'descripcion': 'Montaje y conexionado del tablero principal con llaves termomagnéticas'
        },
        {
            'nombre': 'Colocación de tomas y llaves',
            'descripcion': 'Instalación de tomacorrientes, interruptores y pulsadores'
        },
        {
            'nombre': 'Instalación de luminarias',
            'descripcion': 'Montaje y conexión de artefactos de iluminación'
        },
        {
            'nombre': 'Conexión de electrodomésticos',
            'descripcion': 'Conexión eléctrica de equipos de línea blanca y aires acondicionados'
        },
        {
            'nombre': 'Pruebas y puesta en marcha',
            'descripcion': 'Verificación de funcionamiento y pruebas de seguridad eléctrica'
        }
    ],
    'Instalaciones Sanitarias': [
        {
            'nombre': 'Instalación de cañerías de agua',
            'descripcion': 'Tendido de cañerías de agua fría y caliente en PVC o PPR'
        },
        {
            'nombre': 'Instalación de desagües',
            'descripcion': 'Colocación de cañerías de desagüe cloacal y pluvial'
        },
        {
            'nombre': 'Colocación de artefactos sanitarios',
            'descripcion': 'Instalación de inodoros, lavatorios, bidet y receptáculos'
        },
        {
            'nombre': 'Instalación de grifería',
            'descripcion': 'Montaje de canillas, mezcladores y accesorios de baño'
        },
        {
            'nombre': 'Conexión a red cloacal',
            'descripcion': 'Conexión de desagües a red cloacal municipal o pozo absorbente'
        },
        {
            'nombre': 'Pruebas hidráulicas',
            'descripcion': 'Verificación de funcionamiento y pruebas de presión en instalaciones'
        },
        {
            'nombre': 'Sellado e impermeabilización',
            'descripcion': 'Sellado de uniones y impermeabilización de zonas húmedas'
        }
    ],
    'Instalaciones de Gas': [
        {
            'nombre': 'Tendido de cañería de gas',
            'descripcion': 'Instalación de cañerías de acero o cobre según normativas NAG'
        },
        {
            'nombre': 'Instalación de medidor',
            'descripcion': 'Colocación de medidor y regulador de presión de gas'
        },
        {
            'nombre': 'Conexión de artefactos',
            'descripcion': 'Conexión de cocina, calefón, estufa y otros artefactos a gas'
        },
        {
            'nombre': 'Pruebas de hermeticidad',
            'descripcion': 'Verificación de estanqueidad de toda la instalación de gas'
        },
        {
            'nombre': 'Habilitación con empresa gasífera',
            'descripcion': 'Trámites y habilitación con empresa distribuidora de gas'
        },
        {
            'nombre': 'Señalización de seguridad',
            'descripcion': 'Colocación de señalética de seguridad en instalaciones de gas'
        },
        {
            'nombre': 'Verificación de ventilaciones',
            'descripcion': 'Control de ventilaciones superior e inferior en locales con gas'
        }
    ],
    'Revoque Grueso': [
        {
            'nombre': 'Preparación de superficies',
            'descripcion': 'Limpieza y humedecimiento de muros antes de revocar'
        },
        {
            'nombre': 'Aplicación de revoque grueso exterior',
            'descripcion': 'Aplicación de revoque impermeable en muros exteriores'
        },
        {
            'nombre': 'Aplicación de revoque grueso interior',
            'descripcion': 'Aplicación de revoque de cal y arena en muros interiores'
        },
        {
            'nombre': 'Verificación de verticalidad',
            'descripcion': 'Control de aplome y verticalidad de superficies revocadas'
        },
        {
            'nombre': 'Corrección de imperfecciones',
            'descripcion': 'Reparación de defectos y irregularidades en revoque'
        },
        {
            'nombre': 'Preparación para revoque fino',
            'descripcion': 'Alisado y preparación de superficie para recibir revoque fino'
        },
        {
            'nombre': 'Curado del revoque',
            'descripcion': 'Mantenimiento de humedad para correcto fraguado'
        }
    ],
    'Revoque Fino': [
        {
            'nombre': 'Preparación de mezcla fina',
            'descripcion': 'Preparación de mezcla de cal hidratada y arena fina'
        },
        {
            'nombre': 'Aplicación de revoque fino interior',
            'descripcion': 'Aplicación de capa fina en muros interiores'
        },
        {
            'nombre': 'Aplicación de revoque fino exterior',
            'descripcion': 'Aplicación de revoque fino impermeable en exteriores'
        },
        {
            'nombre': 'Alisado y terminación',
            'descripcion': 'Alisado final con llana para terminación lisa'
        },
        {
            'nombre': 'Corrección de detalles',
            'descripcion': 'Reparación de pequeños defectos y retoques'
        },
        {
            'nombre': 'Preparación para pintura',
            'descripcion': 'Sellado y preparación de superficie para recibir pintura'
        },
        {
            'nombre': 'Limpieza de superficies',
            'descripcion': 'Limpieza final de restos de material y salpicaduras'
        }
    ],
    'Pisos': [
        {
            'nombre': 'Preparación de contrapisos',
            'descripcion': 'Ejecución de contrapisos de hormigón con pendientes'
        },
        {
            'nombre': 'Nivelación de superficies',
            'descripcion': 'Nivelación fina con mortero autonivelante'
        },
        {
            'nombre': 'Colocación de pisos cerámicos',
            'descripcion': 'Instalación de cerámicos con adhesivo especial'
        },
        {
            'nombre': 'Colocación de pisos de madera',
            'descripcion': 'Instalación de pisos de madera maciza o laminada'
        },
        {
            'nombre': 'Instalación de zócalos',
            'descripcion': 'Colocación de zócalos y guardapolvos perimetrales'
        },
        {
            'nombre': 'Sellado de juntas',
            'descripcion': 'Sellado de juntas de dilatación y perimetrales'
        },
        {
            'nombre': 'Limpieza final de pisos',
            'descripcion': 'Limpieza profunda y pulido de pisos terminados'
        }
    ],
    'Carpintería': [
        {
            'nombre': 'Instalación de marcos de puertas',
            'descripcion': 'Colocación de marcos de puertas interiores y exteriores'
        },
        {
            'nombre': 'Instalación de marcos de ventanas',
            'descripcion': 'Montaje de marcos de ventanas de madera o aluminio'
        },
        {
            'nombre': 'Colocación de hojas de puertas',
            'descripcion': 'Instalación de hojas de puertas con bisagras'
        },
        {
            'nombre': 'Colocación de hojas de ventanas',
            'descripcion': 'Montaje de hojas móviles de ventanas'
        },
        {
            'nombre': 'Instalación de herrajes',
            'descripcion': 'Colocación de cerraduras, picaportes y manijas'
        },
        {
            'nombre': 'Ajuste y regulación',
            'descripcion': 'Regulación de apertura y cierre de carpinterías'
        },
        {
            'nombre': 'Sellado perimetral',
            'descripcion': 'Sellado con silicona entre marco y muro'
        }
    ],
    'Pintura': [
        {
            'nombre': 'Preparación de superficies',
            'descripcion': 'Lijado, enduido y preparación de superficies para pintar'
        },
        {
            'nombre': 'Aplicación de imprimación',
            'descripcion': 'Aplicación de sellador y fijador de superficie'
        },
        {
            'nombre': 'Lijado entre manos',
            'descripcion': 'Lijado fino entre capas para mejor terminación'
        },
        {
            'nombre': 'Aplicación de pintura interior',
            'descripcion': 'Aplicación de pintura látex en muros interiores'
        },
        {
            'nombre': 'Aplicación de pintura exterior',
            'descripcion': 'Aplicación de pintura acrílica en muros exteriores'
        },
        {
            'nombre': 'Retoques y detalles',
            'descripcion': 'Retoques finales y pintura de detalles'
        },
        {
            'nombre': 'Limpieza de elementos',
            'descripcion': 'Limpieza de salpicaduras en pisos y carpinterías'
        }
    ],
    'Instalaciones Complementarias': [
        {
            'nombre': 'Instalación de aire acondicionado',
            'descripcion': 'Montaje de equipos split y conductos de aire acondicionado'
        },
        {
            'nombre': 'Instalación de calefacción',
            'descripcion': 'Instalación de sistema de calefacción por radiadores o losa radiante'
        },
        {
            'nombre': 'Instalación de sistema de seguridad',
            'descripcion': 'Instalación de alarmas, cámaras y sensores de seguridad'
        },
        {
            'nombre': 'Instalación de portones automáticos',
            'descripcion': 'Instalación de portones automatizados con motores y controles'
        },
        {
            'nombre': 'Colocación de toldos',
            'descripcion': 'Instalación de toldos retráctiles y fijos'
        },
        {
            'nombre': 'Instalación de sistema de riego',
            'descripcion': 'Instalación de riego automático para jardines'
        },
        {
            'nombre': 'Configuración domótica',
            'descripcion': 'Instalación y configuración de sistemas de automatización del hogar'
        }
    ],
    'Limpieza Final': [
        {
            'nombre': 'Limpieza de obra gruesa',
            'descripcion': 'Retiro de escombros y limpieza general de la obra'
        },
        {
            'nombre': 'Limpieza de vidrios',
            'descripcion': 'Limpieza completa de vidrios y espejos'
        },
        {
            'nombre': 'Limpieza de pisos y superficies',
            'descripcion': 'Limpieza profunda de pisos, azulejos y superficies'
        },
        {
            'nombre': 'Retiro de material sobrante',
            'descripcion': 'Retiro de materiales sobrantes y herramientas'
        },
        {
            'nombre': 'Limpieza de instalaciones',
            'descripcion': 'Limpieza y verificación de funcionamiento de instalaciones'
        },
        {
            'nombre': 'Entrega de documentación',
            'descripcion': 'Entrega de planos conforme a obra y certificados'
        },
        {
            'nombre': 'Inspección final',
            'descripcion': 'Inspección final de calidad y entrega de la obra'
        }
    ]
}

def obtener_tareas_detalladas_para_etapa(nombre_etapa):
    """
    Retorna las tareas predefinidas con descripción para una etapa específica
    """
    return TAREAS_DETALLADAS_POR_ETAPA.get(nombre_etapa, [])