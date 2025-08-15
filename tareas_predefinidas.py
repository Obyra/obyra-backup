# Tareas predefinidas por etapa de construcción
# Basado en la imagen proporcionada por el usuario

TAREAS_POR_ETAPA = {
    'Excavación': [
        {'nombre': 'Replanteo y marcado del terreno', 'descripcion': 'Marcar sobre el terreno las dimensiones y ubicación exacta de la construcción según planos', 'horas': 4},
        {'nombre': 'Excavación para fundaciones', 'descripcion': 'Excavación específica para las bases y fundaciones de la estructura', 'horas': 24},
        {'nombre': 'Excavación para instalaciones subterráneas', 'descripcion': 'Excavación de zanjas para cañerías de agua, cloacas y gas', 'horas': 16},
        {'nombre': 'Nivelación y compactación del terreno', 'descripcion': 'Nivelación y compactación del terreno según cotas del proyecto', 'horas': 8},
        {'nombre': 'Retiro material excavado', 'descripcion': 'Transporte y disposición del material excavado fuera de la obra', 'horas': 12},
        {'nombre': 'Verificación de niveles según planos', 'descripcion': 'Control topográfico y verificación de cotas según documentación técnica', 'horas': 2},
        {'nombre': 'Preparación de base para fundaciones', 'descripcion': 'Acondicionamiento del terreno para recibir las fundaciones', 'horas': 6},
        {'nombre': 'Limpieza y preparación del sitio', 'descripcion': 'Limpieza general del terreno y preparación para inicio de obra', 'horas': 8},
        {'nombre': 'Instalación de cerco perimetral', 'descripcion': 'Colocación de cerco de seguridad alrededor del perímetro de obra', 'horas': 4},
        {'nombre': 'Instalación de servicios temporales', 'descripcion': 'Conexión provisoria de agua, luz y otros servicios necesarios', 'horas': 6},
        {'nombre': 'Estudio de suelos', 'descripcion': 'Análisis del suelo para determinar características y capacidad portante', 'horas': 8},
        {'nombre': 'Verificación de medianeras', 'descripcion': 'Control y verificación de límites del terreno con propiedades lindantes', 'horas': 2},
        {'nombre': 'Demolición de estructuras existentes', 'descripcion': 'Demolición de construcciones existentes que interfieran con el proyecto', 'horas': 16},
        {'nombre': 'Relleno y compactación de terreno', 'descripcion': 'Relleno con material seleccionado y compactación según especificaciones', 'horas': 12},
        {'nombre': 'Drenaje preliminar', 'descripcion': 'Instalación de drenajes temporarios para manejo de aguas', 'horas': 6}
    ],
    
    'Fundaciones': [
        {'nombre': 'Armado de hierros para fundaciones', 'descripcion': 'Preparación y colocación de armaduras de acero según planos estructurales', 'horas': 16},
        {'nombre': 'Colocación de hormigón en fundaciones', 'descripcion': 'Hormigonado de bases y zapatas según especificaciones técnicas', 'horas': 12},
        {'nombre': 'Construcción de bases y zapatas', 'descripcion': 'Construcción de elementos de fundación puntuales', 'horas': 20},
        {'nombre': 'Impermeabilización de fundaciones', 'descripcion': 'Aplicación de membranas impermeabilizantes en fundaciones', 'horas': 8},
        {'nombre': 'Construcción de muros de contención', 'descripcion': 'Construcción de muros para contención de tierras', 'horas': 24},
        {'nombre': 'Verificación de niveles y plomadas', 'descripcion': 'Control topográfico de niveles y verticalidad', 'horas': 4},
        {'nombre': 'Curado del hormigón', 'descripcion': 'Proceso de curado y mantenimiento del hormigón fresco', 'horas': 8},
        {'nombre': 'Excavación de zapatas', 'descripcion': 'Excavación específica para zapatas aisladas', 'horas': 12},
        {'nombre': 'Colocación de piedra desplazadora', 'descripcion': 'Colocación de piedra bruta para economizar hormigón', 'horas': 8},
        {'nombre': 'Armado de encadenados', 'descripcion': 'Armado de hierros para vigas de encadenado', 'horas': 12},
        {'nombre': 'Hormigonado de encadenados', 'descripcion': 'Hormigonado de vigas de encadenado superior', 'horas': 8},
        {'nombre': 'Aislación hidrófuga horizontal', 'descripcion': 'Colocación de aislación hidrófuga horizontal', 'horas': 6},
        {'nombre': 'Relleno con material seleccionado', 'descripcion': 'Relleno con material granular seleccionado', 'horas': 10},
        {'nombre': 'Compactación de rellenos', 'descripcion': 'Compactación mecánica de rellenos', 'horas': 6},
        {'nombre': 'Control de resistencia hormigón', 'descripcion': 'Toma de muestras y control de resistencia', 'horas': 2}
    ],
    
    'Estructura': [
        {'nombre': 'Armado de columnas', 'descripcion': 'Preparación y colocación de armaduras en columnas', 'horas': 20},
        {'nombre': 'Hormigonado de columnas', 'descripcion': 'Hormigonado de columnas con control de calidad', 'horas': 12},
        {'nombre': 'Armado de vigas', 'descripcion': 'Armado de hierros en vigas principales y secundarias', 'horas': 24},
        {'nombre': 'Hormigonado de vigas', 'descripcion': 'Hormigonado de vigas con vibrado adecuado', 'horas': 16},
        {'nombre': 'Armado de losas', 'descripcion': 'Armado de losas con malla de hierro', 'horas': 32},
        {'nombre': 'Hormigonado de losas', 'descripcion': 'Hormigonado de losas con nivelación perfecta', 'horas': 20},
        {'nombre': 'Construcción de escaleras', 'descripcion': 'Construcción de escaleras principales y secundarias', 'horas': 16},
        {'nombre': 'Verificación estructural', 'descripcion': 'Control de calidad y verificación estructural', 'horas': 4},
        {'nombre': 'Colocación de encofrados', 'descripcion': 'Montaje de encofrados para elementos estructurales', 'horas': 24},
        {'nombre': 'Desencofrado y limpieza', 'descripcion': 'Retiro de encofrados y limpieza de superficies', 'horas': 12},
        {'nombre': 'Control de calidad del hormigón', 'descripcion': 'Ensayos y controles de calidad del hormigón', 'horas': 4},
        {'nombre': 'Apuntalamiento temporal', 'descripcion': 'Colocación de puntales temporales de seguridad', 'horas': 8},
        {'nombre': 'Juntas de dilatación', 'descripcion': 'Ejecución de juntas de dilatación estructural', 'horas': 6},
        {'nombre': 'Tratamiento de superficies', 'descripcion': 'Tratamiento y acabado de superficies de hormigón', 'horas': 8},
        {'nombre': 'Nivelación final de losas', 'descripcion': 'Nivelación y alisado final de losas', 'horas': 12}
    ],
    
    'Mampostería': [
        {'nombre': 'Construcción de muros exteriores', 'descripcion': 'Construcción de paredes perimetrales y de fachada', 'horas': 24},
        {'nombre': 'Construcción de muros interiores', 'descripcion': 'Construcción de paredes internas divisorias', 'horas': 16},
        {'nombre': 'Construcción de tabiques divisorios', 'descripcion': 'Construcción de tabiques livianos para división de ambientes', 'horas': 8},
        {'nombre': 'Colocación de dinteles', 'descripcion': 'Instalación de dinteles sobre aberturas de puertas y ventanas', 'horas': 4},
        {'nombre': 'Verificación de aplomes y niveles', 'descripcion': 'Control de verticalidad y horizontalidad de muros', 'horas': 2},
        {'nombre': 'Construcción de antepechos', 'descripcion': 'Construcción de antepechos de ventanas', 'horas': 4},
        {'nombre': 'Preparación para instalaciones', 'descripcion': 'Apertura de rozas y canalizaciones para instalaciones', 'horas': 8},
        {'nombre': 'Colocación de ladrillos', 'descripcion': 'Colocación de ladrillos con mezcla de cemento y arena', 'horas': 32},
        {'nombre': 'Preparación de mortero', 'descripcion': 'Preparación de mezcla para asentamiento de ladrillos', 'horas': 4},
        {'nombre': 'Construcción de columnas de ladrillo', 'descripcion': 'Construcción de columnas de mampostería', 'horas': 12},
        {'nombre': 'Refuerzo de muros con hierro', 'descripcion': 'Colocación de hierros de refuerzo en muros', 'horas': 6},
        {'nombre': 'Construcción de arcos', 'descripcion': 'Construcción de arcos decorativos o estructurales', 'horas': 8},
        {'nombre': 'Limpieza de muros', 'descripcion': 'Limpieza final de muros y retiro de excedentes', 'horas': 4},
        {'nombre': 'Control de calidad mampostería', 'descripcion': 'Verificación final de calidad y terminación', 'horas': 2},
        {'nombre': 'Protección temporal', 'descripcion': 'Protección de muros nuevos contra intemperie', 'horas': 2}
    ],
    
    'Techos': [
        {'nombre': 'Construcción de estructura de techo', 'descripcion': 'Construcción de estructura de madera o acero para cubierta', 'horas': 20},
        {'nombre': 'Colocación de aislación térmica', 'descripcion': 'Instalación de aislamiento térmico en cubierta', 'horas': 8},
        {'nombre': 'Impermeabilización de cubierta', 'descripcion': 'Aplicación de membranas impermeabilizantes', 'horas': 12},
        {'nombre': 'Colocación de tejas o chapa', 'descripcion': 'Instalación de cubierta definitiva de tejas o chapa', 'horas': 16},
        {'nombre': 'Instalación de canaletas', 'descripcion': 'Colocación de canaletas y bajadas pluviales', 'horas': 6},
        {'nombre': 'Construcción de aleros', 'descripcion': 'Construcción de aleros y protecciones', 'horas': 8},
        {'nombre': 'Sellado de juntas y uniones', 'descripcion': 'Sellado de todas las juntas de cubierta', 'horas': 4},
        {'nombre': 'Montaje de tirantes', 'descripcion': 'Montaje de tirantes de madera o acero', 'horas': 12},
        {'nombre': 'Colocación de tableros OSB', 'descripcion': 'Instalación de tableros OSB sobre estructura', 'horas': 8},
        {'nombre': 'Instalación de barrera de vapor', 'descripcion': 'Colocación de barrera de vapor', 'horas': 4},
        {'nombre': 'Ventilación de techos', 'descripcion': 'Instalación de sistemas de ventilación', 'horas': 6},
        {'nombre': 'Aislación acústica', 'descripcion': 'Colocación de aislación acústica', 'horas': 6},
        {'nombre': 'Construcción de claraboyas', 'descripcion': 'Instalación de claraboyas y tragaluces', 'horas': 8},
        {'nombre': 'Protección contra granizo', 'descripcion': 'Instalación de malla antigranizo', 'horas': 4},
        {'nombre': 'Control de calidad cubierta', 'descripcion': 'Verificación final de estanqueidad', 'horas': 2}
    ],
    
    'Instalaciones Eléctricas': [
        {'nombre': 'Canalización eléctrica', 'descripcion': 'Instalación de cañerías y ductos eléctricos', 'horas': 16},
        {'nombre': 'Cableado principal', 'descripcion': 'Tendido de cables principales y ramales', 'horas': 20},
        {'nombre': 'Instalación de tablero eléctrico', 'descripcion': 'Montaje y conexión del tablero principal', 'horas': 8},
        {'nombre': 'Colocación de tomas y llaves', 'descripcion': 'Instalación de tomacorrientes e interruptores', 'horas': 12},
        {'nombre': 'Instalación de luminarias', 'descripcion': 'Montaje de artefactos de iluminación', 'horas': 8},
        {'nombre': 'Conexión de electrodomésticos', 'descripcion': 'Conexión eléctrica de electrodomésticos', 'horas': 4},
        {'nombre': 'Pruebas y puesta en marcha', 'descripcion': 'Ensayos eléctricos y puesta en servicio', 'horas': 6},
        {'nombre': 'Instalación de puesta a tierra', 'descripcion': 'Sistema de puesta a tierra y protección', 'horas': 6},
        {'nombre': 'Cableado de comunicaciones', 'descripcion': 'Instalación de cables de TV, internet y teléfono', 'horas': 8},
        {'nombre': 'Sistema de alarma', 'descripcion': 'Instalación de sistema de seguridad', 'horas': 6},
        {'nombre': 'Automatización domótica', 'descripcion': 'Instalación de sistemas inteligentes', 'horas': 12},
        {'nombre': 'Iluminación exterior', 'descripcion': 'Instalación de iluminación de jardín y fachada', 'horas': 8},
        {'nombre': 'Medición y verificación', 'descripcion': 'Medición de resistencias y continuidad', 'horas': 4},
        {'nombre': 'Protecciones eléctricas', 'descripcion': 'Instalación de disyuntores y protectores', 'horas': 4},
        {'nombre': 'Documentación eléctrica', 'descripcion': 'Elaboración de planos finales as-built', 'horas': 2}
    ],
    
    'Instalaciones Sanitarias': [
        {'nombre': 'Colocación de cañerías de agua', 'descripcion': 'Instalación de cañerías de agua fría y caliente', 'horas': 16},
        {'nombre': 'Instalación de desagües', 'descripcion': 'Colocación de cañerías de desagües cloacales y pluviales', 'horas': 12},
        {'nombre': 'Colocación de sanitarios', 'descripcion': 'Instalación de inodoros, bidés y lavatorios', 'horas': 8},
        {'nombre': 'Prueba de estanqueidad', 'descripcion': 'Pruebas de presión y hermeticidad del sistema', 'horas': 4},
        {'nombre': 'Instalación de grifería', 'descripcion': 'Colocación de canillas, duchas y accesorios', 'horas': 6},
        {'nombre': 'Conexión a red cloacal', 'descripcion': 'Conexión final a la red cloacal municipal', 'horas': 4},
        {'nombre': 'Sellado e impermeabilización', 'descripcion': 'Sellado de juntas y puntos críticos', 'horas': 6}
    ],
    
    'Instalaciones de Gas': [
        {'nombre': 'Colocación de cañerías principales', 'descripcion': 'Tendido de cañería principal de gas natural', 'horas': 12},
        {'nombre': 'Instalación de llaves de paso', 'descripcion': 'Colocación de llaves de corte y seguridad', 'horas': 4},
        {'nombre': 'Prueba de hermeticidad', 'descripcion': 'Pruebas de presión y detección de fugas', 'horas': 6},
        {'nombre': 'Conexión de artefactos', 'descripcion': 'Conexión final de cocinas, calefones y calderas', 'horas': 8},
        {'nombre': 'Instalación de medidor', 'descripcion': 'Colocación del medidor de gas', 'horas': 2},
        {'nombre': 'Habilitación con empresa gasífera', 'descripcion': 'Trámites y habilitación oficial', 'horas': 4},
        {'nombre': 'Verificación de ventilaciones', 'descripcion': 'Control de ventilaciones según normativa', 'horas': 2}
    ],
    
    'Revoque Grueso': [
        {'nombre': 'Preparación de mezcla gruesa', 'descripcion': 'Preparación de mortero para revoque base', 'horas': 2},
        {'nombre': 'Aplicación de capa base', 'descripcion': 'Aplicación de primera capa de revoque grueso', 'horas': 20},
        {'nombre': 'Nivelado de superficie', 'descripcion': 'Nivelación y alisado de superficies', 'horas': 16},
        {'nombre': 'Curado y preparación para capa fina', 'descripcion': 'Curado del revoque y preparación para terminación', 'horas': 8},
        {'nombre': 'Aplicación revoque grueso exterior', 'descripcion': 'Revoque grueso en paredes exteriores', 'horas': 24},
        {'nombre': 'Aplicación revoque grueso interior', 'descripcion': 'Revoque grueso en paredes interiores', 'horas': 16},
        {'nombre': 'Verificación de verticalidad', 'descripcion': 'Control de plomadas y niveles', 'horas': 4}
    ],
    
    'Revoque Fino': [
        {'nombre': 'Preparación de mezcla', 'descripcion': 'Preparación de mortero fino para terminación', 'horas': 2},
        {'nombre': 'Aplicación de capa fina', 'descripcion': 'Aplicación de revoque fino sobre base', 'horas': 18},
        {'nombre': 'Nivelado y alisado', 'descripcion': 'Nivelación perfecta y alisado final', 'horas': 12},
        {'nombre': 'Curado y protección', 'descripcion': 'Curado controlado del revoque fino', 'horas': 6},
        {'nombre': 'Aplicación interior', 'descripcion': 'Revoque fino en ambientes interiores', 'horas': 16},
        {'nombre': 'Aplicación exterior', 'descripcion': 'Revoque fino en fachadas', 'horas': 20},
        {'nombre': 'Preparación para pintura', 'descripcion': 'Lijado y preparación final', 'horas': 8}
    ],
    
    'Pisos': [
        {'nombre': 'Preparación de superficie', 'descripcion': 'Preparación y nivelación de contrapisos', 'horas': 12},
        {'nombre': 'Colocación de baldosas o parquet', 'descripcion': 'Instalación del piso definitivo', 'horas': 24},
        {'nombre': 'Aplicación de fragüe o sellador', 'descripcion': 'Fragüe de juntas y sellado', 'horas': 8},
        {'nombre': 'Pulido y limpieza final', 'descripcion': 'Pulido y limpieza final de pisos', 'horas': 6},
        {'nombre': 'Colocación de pisos cerámicos', 'descripcion': 'Instalación de cerámicos y porcelanatos', 'horas': 20},
        {'nombre': 'Colocación de pisos de madera', 'descripcion': 'Instalación de parquet o deck', 'horas': 18},
        {'nombre': 'Instalación de zócalos', 'descripcion': 'Colocación de zócalos perimetrales', 'horas': 8}
    ],
    
    'Carpintería': [
        {'nombre': 'Medición y corte de piezas', 'descripcion': 'Medición y corte preciso de maderas', 'horas': 8},
        {'nombre': 'Ensamblado de estructuras', 'descripcion': 'Armado y ensamblado de marcos', 'horas': 12},
        {'nombre': 'Colocación de puertas y ventanas', 'descripcion': 'Instalación final de aberturas', 'horas': 16},
        {'nombre': 'Barnizado o pintado de madera', 'descripcion': 'Acabado final de carpintería', 'horas': 10},
        {'nombre': 'Instalación de marcos', 'descripcion': 'Colocación de marcos de puertas y ventanas', 'horas': 12},
        {'nombre': 'Instalación de herrajes', 'descripcion': 'Colocación de bisagras, cerraduras y manijas', 'horas': 6},
        {'nombre': 'Ajuste y regulación', 'descripcion': 'Ajuste final y regulación de aberturas', 'horas': 4}
    ],
    
    'Pintura': [
        {'nombre': 'Lijado de superficies', 'descripcion': 'Lijado y preparación de superficies a pintar', 'horas': 8},
        {'nombre': 'Aplicación de sellador', 'descripcion': 'Aplicación de sellador y fijador', 'horas': 6},
        {'nombre': 'Primera mano de pintura', 'descripcion': 'Aplicación de la primera mano de pintura', 'horas': 12},
        {'nombre': 'Segunda mano de pintura', 'descripcion': 'Aplicación de mano final de pintura', 'horas': 10},
        {'nombre': 'Revisión y retoques finales', 'descripcion': 'Inspección final y corrección de detalles', 'horas': 6},
        {'nombre': 'Pintura interior', 'descripcion': 'Pintura completa de ambientes interiores', 'horas': 16},
        {'nombre': 'Pintura exterior', 'descripcion': 'Pintura de fachadas y exteriores', 'horas': 20}
    ],
    
    'Instalaciones Complementarias': [
        {'nombre': 'Instalación de aire acondicionado', 'descripcion': 'Montaje de equipos de climatización', 'horas': 12},
        {'nombre': 'Instalación de calefacción', 'descripcion': 'Sistema de calefacción central o individual', 'horas': 16},
        {'nombre': 'Instalación de sistema de seguridad', 'descripcion': 'Alarmas, cámaras y sistemas de monitoreo', 'horas': 10},
        {'nombre': 'Instalación de portones automáticos', 'descripcion': 'Automatización de portones y accesos', 'horas': 8},
        {'nombre': 'Colocación de toldos', 'descripcion': 'Instalación de toldos y protecciones solares', 'horas': 6},
        {'nombre': 'Instalación de sistema de riego', 'descripcion': 'Sistema de riego automático para jardines', 'horas': 12},
        {'nombre': 'Configuración domótica', 'descripcion': 'Programación de sistemas inteligentes', 'horas': 8}
    ],
    
    'Limpieza Final': [
        {'nombre': 'Limpieza de obra gruesa', 'descripcion': 'Limpieza general y retiro de escombros', 'horas': 12},
        {'nombre': 'Limpieza de vidrios', 'descripcion': 'Limpieza de todas las superficies vidriadas', 'horas': 6},
        {'nombre': 'Limpieza de pisos y superficies', 'descripcion': 'Limpieza profunda de pisos y superficies', 'horas': 8},
        {'nombre': 'Retiro de material sobrante', 'descripcion': 'Retiro final de materiales y herramientas', 'horas': 4},
        {'nombre': 'Limpieza de instalaciones', 'descripcion': 'Limpieza de sanitarios y instalaciones', 'horas': 4},
        {'nombre': 'Entrega de documentación', 'descripcion': 'Preparación de documentación de entrega', 'horas': 2},
        {'nombre': 'Inspección final', 'descripcion': 'Inspección final y lista de pendientes', 'horas': 4}
    ]
}

def obtener_tareas_por_etapa(nombre_etapa):
    """Obtiene las tareas predefinidas para una etapa específica"""
    return TAREAS_POR_ETAPA.get(nombre_etapa, [])

def obtener_todas_las_etapas_con_tareas():
    """Retorna todas las etapas con sus tareas asociadas"""
    return TAREAS_POR_ETAPA