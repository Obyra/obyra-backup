"""
Tareas predefinidas por etapa de construcción con descripciones detalladas - OBYRA IA
"""

# Tareas predefinidas por tipo de etapa con descripciones detalladas
TAREAS_DETALLADAS_POR_ETAPA = {
    'Excavación': [
        {
            'nombre': 'Replanteo y marcación del terreno',
            'descripcion': 'Marcar sobre el terreno las dimensiones y ubicación exacta de la construcción según planos'
        },
        {
            'nombre': 'Excavación manual de zanjas',
            'descripcion': 'Excavación a mano de zanjas para fundaciones en áreas de difícil acceso para maquinaria'
        },
        {
            'nombre': 'Excavación mecánica',
            'descripcion': 'Excavación con retroexcavadora o pala mecánica para movimiento de grandes volúmenes de tierra'
        },
        {
            'nombre': 'Nivelación del terreno',
            'descripcion': 'Nivelación y compactación del terreno según cotas establecidas en el proyecto'
        },
        {
            'nombre': 'Verificación de cotas y niveles',
            'descripcion': 'Control topográfico de niveles y verificación de medidas según planos de obra'
        }
    ],
    'Fundaciones': [
        {
            'nombre': 'Armado de hierros para fundaciones',
            'descripcion': 'Preparación y colocación de armaduras de acero según planos estructurales'
        },
        {
            'nombre': 'Colocación de encofrado',
            'descripcion': 'Instalación de moldes de madera o metal para dar forma al hormigón'
        },
        {
            'nombre': 'Hormigonado de fundaciones',
            'descripcion': 'Vertido y vibrado del hormigón en fundaciones según especificaciones técnicas'
        },
        {
            'nombre': 'Curado del hormigón',
            'descripcion': 'Mantenimiento de humedad y temperatura para el correcto fraguado del hormigón'
        },
        {
            'nombre': 'Desencofrado',
            'descripcion': 'Retiro de encofrados una vez alcanzada la resistencia mínima del hormigón'
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
        }
    ],
    'Mampostería': [
        {
            'nombre': 'Replanteo de muros',
            'descripcion': 'Marcación de la ubicación y dimensiones de muros según planos'
        },
        {
            'nombre': 'Colocación de ladrillos',
            'descripcion': 'Construcción de muros con ladrillos, bloques o materiales similares'
        },
        {
            'nombre': 'Construcción de dinteles',
            'descripcion': 'Instalación de elementos estructurales sobre aberturas'
        },
        {
            'nombre': 'Instalación de marcos de puertas',
            'descripcion': 'Colocación y ajuste de marcos para puertas interiores y exteriores'
        },
        {
            'nombre': 'Instalación de marcos de ventanas',
            'descripcion': 'Colocación de marcos de ventanas con sellado y aislación'
        }
    ],
    'Techos': [
        {
            'nombre': 'Armado de estructura de techo',
            'descripcion': 'Construcción de estructura portante del techo (cabriadas, correas, etc.)'
        },
        {
            'nombre': 'Colocación de chapas/tejas',
            'descripcion': 'Instalación del material de cubierta según especificaciones'
        },
        {
            'nombre': 'Instalación de canaletas',
            'descripcion': 'Colocación de sistema de desagüe pluvial'
        },
        {
            'nombre': 'Impermeabilización',
            'descripcion': 'Aplicación de materiales impermeabilizantes en cubierta'
        },
        {
            'nombre': 'Aislación térmica',
            'descripcion': 'Instalación de materiales aislantes para eficiencia energética'
        }
    ],
    'Instalaciones Eléctricas': [
        {
            'nombre': 'Replanteo de circuitos eléctricos',
            'descripcion': 'Marcación de recorridos de cables y ubicación de componentes eléctricos'
        },
        {
            'nombre': 'Canalización eléctrica',
            'descripcion': 'Instalación de caños y conductos para el paso de cables'
        },
        {
            'nombre': 'Cableado principal',
            'descripcion': 'Tendido de cables desde tablero principal a puntos de consumo'
        },
        {
            'nombre': 'Instalación de tablero eléctrico',
            'descripcion': 'Montaje y conexionado del tablero principal con protecciones'
        },
        {
            'nombre': 'Colocación de tomas y llaves',
            'descripcion': 'Instalación de tomacorrientes, interruptores y llaves de luz'
        },
        {
            'nombre': 'Conexión de artefactos',
            'descripcion': 'Conexión de luminarias y equipos eléctricos'
        },
        {
            'nombre': 'Pruebas y verificaciones',
            'descripcion': 'Control de funcionamiento y mediciones eléctricas de seguridad'
        }
    ],
    'Instalaciones Sanitarias': [
        {
            'nombre': 'Replanteo de instalaciones',
            'descripcion': 'Marcación de recorridos de cañerías y ubicación de artefactos'
        },
        {
            'nombre': 'Instalación de cañerías de agua',
            'descripcion': 'Tendido de cañerías de agua fría y caliente'
        },
        {
            'nombre': 'Instalación de desagües',
            'descripcion': 'Colocación de cañerías de desagüe cloacal y pluvial'
        },
        {
            'nombre': 'Colocación de artefactos sanitarios',
            'descripcion': 'Instalación de inodoros, lavatorios, bachas y grifería'
        },
        {
            'nombre': 'Conexión a red pública',
            'descripcion': 'Conexión a redes de agua potable y cloacas municipales'
        },
        {
            'nombre': 'Pruebas hidráulicas',
            'descripcion': 'Verificación de funcionamiento y pruebas de presión'
        }
    ],
    'Instalaciones de Gas': [
        {
            'nombre': 'Replanteo de instalación de gas',
            'descripcion': 'Marcación del recorrido de cañerías de gas según normativas'
        },
        {
            'nombre': 'Instalación de cañerías',
            'descripcion': 'Tendido de cañerías de gas con uniones y conexiones reglamentarias'
        },
        {
            'nombre': 'Colocación de regulador',
            'descripcion': 'Instalación de regulador de presión y medidor de gas'
        },
        {
            'nombre': 'Instalación de artefactos',
            'descripcion': 'Conexión de artefactos a gas (cocina, calefón, etc.)'
        },
        {
            'nombre': 'Pruebas de estanqueidad',
            'descripcion': 'Verificación de hermeticidad de toda la instalación'
        },
        {
            'nombre': 'Habilitación por gasista matriculado',
            'descripcion': 'Certificación final de la instalación por profesional habilitado'
        }
    ],
    'Revoque Grueso': [
        {
            'nombre': 'Preparación de superficies',
            'descripcion': 'Limpieza y preparación de muros para aplicación de revoque'
        },
        {
            'nombre': 'Aplicación de revoque grueso',
            'descripcion': 'Aplicación de primera capa de revoque para nivelación'
        },
        {
            'nombre': 'Nivelación y alisado',
            'descripcion': 'Nivelación de superficies con regla y alisado inicial'
        },
        {
            'nombre': 'Curado del revoque',
            'descripcion': 'Mantenimiento de humedad para correcto fraguado del revoque'
        }
    ],
    'Revoque Fino': [
        {
            'nombre': 'Preparación de superficie',
            'descripcion': 'Limpieza y humedecimiento del revoque grueso'
        },
        {
            'nombre': 'Aplicación de revoque fino',
            'descripcion': 'Aplicación de capa final de revoque para terminación'
        },
        {
            'nombre': 'Alisado y terminación',
            'descripcion': 'Alisado final con llana para obtener superficie lisa'
        },
        {
            'nombre': 'Control de calidad',
            'descripcion': 'Verificación de planeidad y acabado superficial'
        }
    ],
    'Pisos': [
        {
            'nombre': 'Preparación del contrapiso',
            'descripcion': 'Nivelación y preparación de base para colocación de pisos'
        },
        {
            'nombre': 'Nivelación',
            'descripcion': 'Verificación y corrección de niveles con mortero de nivelación'
        },
        {
            'nombre': 'Colocación de pisos',
            'descripcion': 'Instalación de revestimiento de piso según especificaciones'
        },
        {
            'nombre': 'Instalación de zócalos',
            'descripcion': 'Colocación de zócalos perimetrales y guardapolvos'
        },
        {
            'nombre': 'Limpieza final',
            'descripcion': 'Limpieza y pulido final del piso instalado'
        }
    ],
    'Carpintería': [
        {
            'nombre': 'Instalación de puertas interiores',
            'descripcion': 'Colocación y ajuste de puertas internas con herrajes'
        },
        {
            'nombre': 'Instalación de ventanas',
            'descripcion': 'Montaje de ventanas con vidrios y herrajes de apertura'
        },
        {
            'nombre': 'Colocación de marcos',
            'descripcion': 'Instalación de marcos de madera o aluminio'
        },
        {
            'nombre': 'Instalación de herrajes',
            'descripcion': 'Colocación de cerraduras, bisagras y accesorios'
        },
        {
            'nombre': 'Ajustes finales',
            'descripcion': 'Regulación y ajuste final de puertas y ventanas'
        }
    ],
    'Pintura': [
        {
            'nombre': 'Preparación de superficies',
            'descripcion': 'Lijado, limpieza y reparación de superficies a pintar'
        },
        {
            'nombre': 'Aplicación de imprimación',
            'descripcion': 'Aplicación de base o fijador según tipo de superficie'
        },
        {
            'nombre': 'Primera mano de pintura',
            'descripcion': 'Aplicación de primera capa de pintura de acabado'
        },
        {
            'nombre': 'Segunda mano de pintura',
            'descripcion': 'Aplicación de segunda capa para terminación final'
        },
        {
            'nombre': 'Retoques finales',
            'descripcion': 'Corrección de detalles y retoques de terminación'
        }
    ],
    'Instalaciones Complementarias': [
        {
            'nombre': 'Instalación de aire acondicionado',
            'descripcion': 'Montaje de equipos de climatización y cañerías frigoríficas'
        },
        {
            'nombre': 'Sistema de calefacción',
            'descripcion': 'Instalación de sistema de calefacción central o individual'
        },
        {
            'nombre': 'Instalaciones especiales',
            'descripcion': 'Sistemas de seguridad, domótica o instalaciones específicas'
        },
        {
            'nombre': 'Pruebas de funcionamiento',
            'descripcion': 'Verificación del correcto funcionamiento de todos los sistemas'
        }
    ]
}

def obtener_tareas_detalladas_para_etapa(nombre_etapa):
    """
    Retorna las tareas predefinidas con descripción para una etapa específica
    """
    return TAREAS_DETALLADAS_POR_ETAPA.get(nombre_etapa, [])