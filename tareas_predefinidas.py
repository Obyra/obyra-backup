# Tareas predefinidas por etapa de construcción
# Basado en la imagen proporcionada por el usuario
# Actualizado con 13 etapas nuevas y tareas adicionales para etapas existentes

import re
import unicodedata


def _slugify_etapa(nombre: str) -> str:
    """Normaliza un nombre de etapa a un slug ASCII en minúsculas."""

    if not nombre:
        return ""
    normalized = unicodedata.normalize("NFKD", nombre)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized.lower())
    return normalized.strip("-")


TAREAS_POR_ETAPA = {
    # =========================================================================
    # ETAPAS NUEVAS
    # =========================================================================

    'Preliminares y Obrador': [
        {'nombre': 'Gestión de permisos municipales', 'descripcion': 'Tramitar permiso de obra y cartel de obra', 'horas': 8},
        {'nombre': 'Armar obrador', 'descripcion': 'Instalar oficina, vestuario y sanitario de obra', 'horas': 16},
        {'nombre': 'Cerco perimetral de obra', 'descripcion': 'Colocar vallado provisorio en todo el perímetro', 'horas': 6},
        {'nombre': 'Conexión provisoria de agua', 'descripcion': 'Instalar toma de agua temporaria para obra', 'horas': 4},
        {'nombre': 'Conexión provisoria de electricidad', 'descripcion': 'Instalar tablero y acometida eléctrica temporaria', 'horas': 6},
        {'nombre': 'Replanteo general', 'descripcion': 'Marcar ejes, niveles y líneas de edificación', 'horas': 8},
        {'nombre': 'Cartel de obra', 'descripcion': 'Colocar cartel reglamentario en frente de obra', 'horas': 2},
        {'nombre': 'Plan de seguridad e higiene', 'descripcion': 'Elaborar y presentar plan de SyH ante ART', 'horas': 8},
        {'nombre': 'Relevamiento topográfico', 'descripcion': 'Realizar planialtimetría del terreno', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Desratización y desinfección', 'descripcion': 'Sanitizar terreno previo al inicio', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Acopio de materiales inicial', 'descripcion': 'Organizar zona de acopio y recepción', 'horas': 4},
        {'nombre': 'Instalación de guinche / grúa', 'descripcion': 'Montar equipo de elevación vertical', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Verificación de medianeras', 'descripcion': 'Constatar estado y altura de muros linderos', 'horas': 4},
        {'nombre': 'Registro fotográfico inicial', 'descripcion': 'Documentar estado previo del terreno y linderos', 'horas': 2},
    ],

    'Demoliciones': [
        {'nombre': 'Relevamiento de estructuras a demoler', 'descripcion': 'Identificar elementos a demoler según proyecto', 'horas': 4},
        {'nombre': 'Corte de servicios existentes', 'descripcion': 'Desconectar agua, gas, electricidad y cloacas', 'horas': 4},
        {'nombre': 'Demolición de mampostería', 'descripcion': 'Demoler muros y tabiques existentes', 'horas': 16},
        {'nombre': 'Demolición de losas y vigas', 'descripcion': 'Demoler estructura de hormigón armado', 'horas': 24, 'si_aplica': True},
        {'nombre': 'Demolición de pisos existentes', 'descripcion': 'Retirar solados, contrapisos y bases', 'horas': 12},
        {'nombre': 'Demolición de cubiertas', 'descripcion': 'Desmontar techos, chapas y estructuras', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Retiro de carpinterías existentes', 'descripcion': 'Desmontar puertas, ventanas y marcos', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Retiro de instalaciones existentes', 'descripcion': 'Desmontar cañerías, cables y artefactos', 'horas': 8},
        {'nombre': 'Clasificación de escombros', 'descripcion': 'Separar material reutilizable del descarte', 'horas': 4},
        {'nombre': 'Carga y retiro de escombros', 'descripcion': 'Cargar volquetes y retirar material de obra', 'horas': 8},
        {'nombre': 'Apuntalamiento preventivo', 'descripcion': 'Apuntalar elementos a conservar durante demolición', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Protección de linderos', 'descripcion': 'Proteger medianeras y propiedades vecinas', 'horas': 4},
    ],

    'Movimiento de Suelos': [
        {'nombre': 'Desmalezamiento y limpieza vegetal', 'descripcion': 'Retirar vegetación, raíces y capa orgánica', 'horas': 6},
        {'nombre': 'Destape y retiro de capa vegetal', 'descripcion': 'Extraer tierra vegetal hasta suelo firme', 'horas': 8},
        {'nombre': 'Excavación masiva con máquina', 'descripcion': 'Excavar a nivel general con retroexcavadora', 'horas': 24},
        {'nombre': 'Excavación selectiva manual', 'descripcion': 'Excavar sectores puntuales con mano de obra', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Relleno con material seleccionado', 'descripcion': 'Rellenar y nivelar con tosca o suelo seleccionado', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Compactación mecánica', 'descripcion': 'Compactar con rodillo o pata de cabra', 'horas': 8},
        {'nombre': 'Control de compactación (Proctor)', 'descripcion': 'Realizar ensayo de densidad en capas', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Perfilado de taludes', 'descripcion': 'Dar pendiente y forma a cortes del terreno', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Terraplenado', 'descripcion': 'Elevar nivel de terreno con relleno compactado', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Transporte de suelo excedente', 'descripcion': 'Retirar material sobrante a destino autorizado', 'horas': 8},
        {'nombre': 'Nivelación final del terreno', 'descripcion': 'Dejar superficie a cota de proyecto', 'horas': 6},
    ],

    'Apuntalamientos': [
        {'nombre': 'Apuntalamiento de medianeras', 'descripcion': 'Sostener muros linderos durante excavación', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Apuntalamiento de losas', 'descripcion': 'Apuntalar losas durante hormigonado y fraguado', 'horas': 12},
        {'nombre': 'Apuntalamiento de vigas', 'descripcion': 'Sostener vigas hasta alcanzar resistencia', 'horas': 8},
        {'nombre': 'Apuntalamiento de encofrados', 'descripcion': 'Apuntalar moldes para hormigón armado', 'horas': 10},
        {'nombre': 'Arriostrado de excavaciones', 'descripcion': 'Colocar puntales cruzados en zanjas profundas', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Control de deformaciones', 'descripcion': 'Monitorear movimientos con testigos y niveles', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Retiro progresivo de puntales', 'descripcion': 'Desapuntalar según orden estructural indicado', 'horas': 8},
        {'nombre': 'Apuntalamiento de estructuras existentes', 'descripcion': 'Sostener elementos durante refuerzos o reformas', 'horas': 12, 'si_aplica': True},
    ],

    'Depresión de Napa / Bombeo': [
        {'nombre': 'Estudio de nivel freático', 'descripcion': 'Determinar profundidad de napa mediante cateos', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Instalación de well points', 'descripcion': 'Colocar sistema de agujas filtrantes perimetrales', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Instalación de bombas sumergibles', 'descripcion': 'Colocar bombas en pozos de achique', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Excavación de pozo de bombeo', 'descripcion': 'Excavar pozo sumidero para concentrar agua', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Operación y control de bombeo', 'descripcion': 'Mantener bombeo continuo durante fundaciones', 'horas': 24, 'si_aplica': True},
        {'nombre': 'Canalización de agua extraída', 'descripcion': 'Conducir agua bombeada a desagüe autorizado', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Retiro de equipo de bombeo', 'descripcion': 'Desmontar sistema una vez hormigonadas las fundaciones', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Drenaje subterráneo permanente', 'descripcion': 'Instalar drenes perimetrales definitivos', 'horas': 12, 'si_aplica': True},
    ],

    'Construcción en Seco': [
        {'nombre': 'Montaje de estructura Steel Frame', 'descripcion': 'Armar estructura portante de perfiles de acero', 'horas': 32, 'si_aplica': True},
        {'nombre': 'Montaje de estructura Wood Frame', 'descripcion': 'Armar estructura portante de madera', 'horas': 32, 'si_aplica': True},
        {'nombre': 'Tabiques de roca de yeso (Durlock)', 'descripcion': 'Montar tabiques divisorios con placas de yeso', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Cielorrasos de roca de yeso', 'descripcion': 'Montar cielorrasos suspendidos con placas', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Revestimiento de roca de yeso en muros', 'descripcion': 'Revestir muros existentes con placas de yeso', 'horas': 10, 'si_aplica': True},
        {'nombre': 'Aislación interior de tabiques', 'descripcion': 'Colocar lana de vidrio o EPS dentro del tabique', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Masillado de juntas y tornillos', 'descripcion': 'Tratar uniones y fijaciones con masilla y cinta', 'horas': 8},
        {'nombre': 'Colocación de refuerzos para cargas', 'descripcion': 'Instalar refuerzos metálicos para muebles o TV', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Cenefas y nichos', 'descripcion': 'Construir detalles decorativos con placas', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Impermeabilización de placas en zonas húmedas', 'descripcion': 'Tratar placas verdes con membrana en baños', 'horas': 4, 'si_aplica': True},
    ],

    'Ventilaciones y Conductos': [
        {'nombre': 'Construcción de conductos de ventilación', 'descripcion': 'Levantar conductos de mampostería reglamentarios', 'horas': 12},
        {'nombre': 'Instalación de conductos de chapa', 'descripcion': 'Colocar conductos metálicos para extracción', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Colocación de sombrerete', 'descripcion': 'Instalar remate superior del conducto en techo', 'horas': 2},
        {'nombre': 'Ventilación de baños', 'descripcion': 'Conectar baños a conducto o ventilación directa', 'horas': 4},
        {'nombre': 'Ventilación de cocinas', 'descripcion': 'Instalar conducto de extracción sobre cocina', 'horas': 4},
        {'nombre': 'Ventilación de calefactores', 'descripcion': 'Asegurar tiro balanceado o conducto de evacuación', 'horas': 4},
        {'nombre': 'Conductos de aire acondicionado', 'descripcion': 'Instalar ductos de distribución de AA central', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Rejillas de ventilación', 'descripcion': 'Colocar rejillas de ingreso y egreso de aire', 'horas': 4},
        {'nombre': 'Verificación de tiro', 'descripcion': 'Probar tiraje con humo en cada conducto', 'horas': 2},
        {'nombre': 'Conductos para campanas extractoras', 'descripcion': 'Instalar conductos de extracción para cocinas', 'horas': 6, 'si_aplica': True},
    ],

    'Impermeabilizaciones y Aislaciones': [
        {'nombre': 'Aislación hidrófuga horizontal en fundaciones', 'descripcion': 'Colocar membrana o pintura asfáltica en cimientos', 'horas': 8},
        {'nombre': 'Aislación hidrófuga vertical en muros enterrados', 'descripcion': 'Impermeabilizar muros en contacto con suelo', 'horas': 10, 'si_aplica': True},
        {'nombre': 'Membrana asfáltica en techos', 'descripcion': 'Colocar membrana con solape y sellado de juntas', 'horas': 12},
        {'nombre': 'Membrana líquida en balcones', 'descripcion': 'Aplicar impermeabilizante en balcones y terrazas', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Azotado hidrófugo en baños y cocinas', 'descripcion': 'Aplicar capa hidrófuga sobre mampostería húmeda', 'horas': 8},
        {'nombre': 'Barrera de vapor en cubiertas', 'descripcion': 'Colocar film de polietileno bajo aislación térmica', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Aislación térmica en muros', 'descripcion': 'Colocar poliestireno expandido o lana de vidrio', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Aislación térmica en techos', 'descripcion': 'Colocar aislante térmico sobre losa o bajo cubierta', 'horas': 8},
        {'nombre': 'Aislación acústica en muros divisorios', 'descripcion': 'Colocar material fonoabsorbente entre tabiques', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Aislación acústica en losas', 'descripcion': 'Colocar manta o membrana acústica bajo piso', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Sellado de juntas de dilatación', 'descripcion': 'Sellar juntas con material elastomérico', 'horas': 4},
        {'nombre': 'Tratamiento de fisuras', 'descripcion': 'Sellar fisuras existentes con resinas o morteros', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Pintura asfáltica en subsuelos', 'descripcion': 'Aplicar asfalto en muros y pisos de subsuelo', 'horas': 8, 'si_aplica': True},
    ],

    'Cielorrasos': [
        {'nombre': 'Cielorraso aplicado de yeso', 'descripcion': 'Aplicar yeso a la cal directamente sobre losa', 'horas': 16},
        {'nombre': 'Cielorraso suspendido de placas de yeso', 'descripcion': 'Montar estructura y placas de roca de yeso', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Cielorraso desmontable', 'descripcion': 'Instalar estructura y placas removibles tipo Armstrong', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Cielorraso de madera (machimbre)', 'descripcion': 'Colocar tablas machihembradas sobre estructura', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Cielorraso de PVC', 'descripcion': 'Instalar paneles de PVC sobre perfilería', 'horas': 10, 'si_aplica': True},
        {'nombre': 'Molduras y cornisas', 'descripcion': 'Colocar molduras decorativas en encuentro pared-cielorraso', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Tabica y cenefa en cielorrasos', 'descripcion': 'Realizar bajadas y detalles de iluminación indirecta', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Masillado y lijado de juntas', 'descripcion': 'Tratar juntas de placas antes de pintura', 'horas': 6},
        {'nombre': 'Colocación de trampas de inspección', 'descripcion': 'Instalar tapas de acceso a instalaciones ocultas', 'horas': 2, 'si_aplica': True},
    ],

    'Yesería y Enlucidos': [
        {'nombre': 'Enlucido de yeso en paredes', 'descripcion': 'Aplicar terminación de yeso sobre revoque grueso', 'horas': 18},
        {'nombre': 'Enlucido de yeso en cielorrasos', 'descripcion': 'Aplicar yeso como terminación en techos', 'horas': 12},
        {'nombre': 'Fajas y maestras de yeso', 'descripcion': 'Ejecutar guías de nivel para el enlucido', 'horas': 6},
        {'nombre': 'Reparación de fisuras con yeso', 'descripcion': 'Tratar fisuras y grietas con vendas y yeso', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Molduras de yeso decorativas', 'descripcion': 'Colocar molduras, rosetas y cornisas', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Estucado', 'descripcion': 'Aplicar estuco veneciano o símil en paredes', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Jaharro cementicio', 'descripcion': 'Aplicar capa de regularización con mortero cementicio', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Preparación de superficies para pintura', 'descripcion': 'Lijar, emparchar y sellar antes de pintar', 'horas': 8},
    ],

    'Contrapisos y Carpetas': [
        {'nombre': 'Contrapiso sobre terreno natural', 'descripcion': 'Ejecutar capa de hormigón pobre sobre suelo', 'horas': 16},
        {'nombre': 'Contrapiso sobre losa', 'descripcion': 'Ejecutar capa de nivelación sobre losa de entrepiso', 'horas': 12},
        {'nombre': 'Contrapiso liviano', 'descripcion': 'Ejecutar con arcilla expandida o EPS para menor peso', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Carpeta de nivelación', 'descripcion': 'Aplicar mortero de arena y cemento para nivelar', 'horas': 10},
        {'nombre': 'Carpeta hidrófuga', 'descripcion': 'Ejecutar carpeta con aditivo hidrófugo en zonas húmedas', 'horas': 8},
        {'nombre': 'Pendientes para desagüe', 'descripcion': 'Ejecutar pendientes hacia bocas de desagüe en baños/balcones', 'horas': 6},
        {'nombre': 'Contrapiso en azoteas', 'descripcion': 'Ejecutar contrapiso con pendiente para escurrimiento', 'horas': 10, 'si_aplica': True},
        {'nombre': 'Juntas de dilatación en contrapisos', 'descripcion': 'Cortar o colocar perfiles de junta cada 16 m2', 'horas': 4},
        {'nombre': 'Curado de contrapisos', 'descripcion': 'Humedecer y proteger superficie durante fraguado', 'horas': 4},
    ],

    'Revestimientos': [
        {'nombre': 'Revestimiento cerámico en baños', 'descripcion': 'Colocar cerámicos en paredes de baños completos', 'horas': 16},
        {'nombre': 'Revestimiento cerámico en cocinas', 'descripcion': 'Colocar cerámicos en salpicadero y zona de mesada', 'horas': 8},
        {'nombre': 'Revestimiento de porcellanato', 'descripcion': 'Colocar porcellanato en pisos y paredes', 'horas': 20, 'si_aplica': True},
        {'nombre': 'Revestimiento de piedra natural', 'descripcion': 'Colocar mármol, granito o travertino', 'horas': 24, 'si_aplica': True},
        {'nombre': 'Revestimiento de piedra reconstituida', 'descripcion': 'Colocar placas símil piedra en fachadas o interiores', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Revoque plástico texturado', 'descripcion': 'Aplicar revoque plástico en fachadas', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Colocación de guardas decorativas', 'descripcion': 'Instalar guardas o filetes entre cerámicos', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Colocación de zócalos cerámicos', 'descripcion': 'Colocar zócalo perimetral en ambientes', 'horas': 6},
        {'nombre': 'Revestimiento de piletas', 'descripcion': 'Colocar venecitas o cerámicos en natatorios', 'horas': 24, 'si_aplica': True},
        {'nombre': 'Pastina y tomado de juntas', 'descripcion': 'Aplicar pastina en juntas de cerámicos', 'horas': 6},
        {'nombre': 'Protección de aristas (guardacantos)', 'descripcion': 'Colocar perfiles de aluminio en esquinas y bordes', 'horas': 4},
    ],

    'Provisiones y Colocaciones': [
        {'nombre': 'Colocación de mesadas', 'descripcion': 'Instalar mesadas de granito, mármol o cuarzo', 'horas': 8},
        {'nombre': 'Colocación de griferías', 'descripcion': 'Instalar griferías en baños y cocina', 'horas': 6},
        {'nombre': 'Colocación de sanitarios', 'descripcion': 'Instalar inodoro, bidet, lavatorio y bañera', 'horas': 8},
        {'nombre': 'Colocación de accesorios de baño', 'descripcion': 'Instalar jaboneras, toalleros, portarrollos', 'horas': 4},
        {'nombre': 'Colocación de espejos', 'descripcion': 'Instalar espejos en baños y toilettes', 'horas': 2},
        {'nombre': 'Colocación de herrajes de carpintería', 'descripcion': 'Instalar cerraduras, bisagras y manijas', 'horas': 6},
        {'nombre': 'Colocación de vidrios y cristales', 'descripcion': 'Instalar vidrios en carpinterías y mamparas', 'horas': 8},
        {'nombre': 'Colocación de barandas y pasamanos', 'descripcion': 'Instalar barandas en escaleras y balcones', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Colocación de tapas de inspección', 'descripcion': 'Instalar tapas en pisos y paredes para acceso a instalaciones', 'horas': 4},
        {'nombre': 'Colocación de rejillas de piso', 'descripcion': 'Instalar rejillas en baños, balcones y patios', 'horas': 4},
        {'nombre': 'Colocación de solías y umbrales', 'descripcion': 'Instalar solías en ventanas y umbrales en puertas', 'horas': 6},
        {'nombre': 'Colocación de burletes y selladores', 'descripcion': 'Sellar carpinterías contra filtraciones', 'horas': 4},
        {'nombre': 'Colocación de topes de puerta', 'descripcion': 'Instalar topes en pisos o paredes', 'horas': 2},
        {'nombre': 'Numeración de unidades funcionales', 'descripcion': 'Colocar numeración en puertas de departamentos', 'horas': 2, 'si_aplica': True},
        {'nombre': 'Buzones', 'descripcion': 'Instalar buzones individuales o rack de buzones', 'horas': 4, 'si_aplica': True},
    ],

    # =========================================================================
    # ETAPAS EXISTENTES (con tareas originales + nuevas agregadas al final)
    # =========================================================================

    'Excavación': [
        # --- Tareas originales ---
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
        {'nombre': 'Drenaje preliminar', 'descripcion': 'Instalación de drenajes temporarios para manejo de aguas', 'horas': 6},
        # --- Tareas nuevas ---
        {'nombre': 'Cateos de suelo', 'descripcion': 'Realizar pozos exploratorios para verificar tipo de suelo', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Troneras en medianeras', 'descripcion': 'Ejecutar perforaciones en muros para pasaje de vigas', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Excavación para platea', 'descripcion': 'Excavar a nivel uniforme para fundación tipo platea', 'horas': 20, 'si_aplica': True},
        {'nombre': 'Excavación de vigas de fundación', 'descripcion': 'Excavar zanjas para vigas de arriostramiento', 'horas': 12},
        {'nombre': 'Excavación de pozos absorbentes', 'descripcion': 'Excavar pozos para sistema de absorción cloacal', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Perfilado manual de zanjas', 'descripcion': 'Regularizar fondo y laterales de excavaciones a mano', 'horas': 6},
        {'nombre': 'Excavación para cisterna', 'descripcion': 'Excavar pozo para tanque de reserva subterráneo', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Excavación para ascensor', 'descripcion': 'Excavar pozo para recorrido inferior del ascensor', 'horas': 16, 'si_aplica': True},
    ],

    'Fundaciones': [
        # --- Tareas originales ---
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
        {'nombre': 'Control de resistencia hormigón', 'descripcion': 'Toma de muestras y control de resistencia', 'horas': 2},
        # --- Tareas nuevas ---
        {'nombre': 'Submuración de medianeras', 'descripcion': 'Recalzar fundaciones existentes de muros linderos', 'horas': 24, 'si_aplica': True},
        {'nombre': 'Tabiques de empuje (contención)', 'descripcion': 'Construir muros de contención de empuje de suelos', 'horas': 20, 'si_aplica': True},
        {'nombre': 'Pilotes de tracción', 'descripcion': 'Ejecutar pilotes para contrarrestar empuje ascendente', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Tesado de cables post-tensados', 'descripcion': 'Tensar cables en fundaciones post-tensadas', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Bajo recorrido de ascensor', 'descripcion': 'Construir fosa y estructura inferior del ascensor', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Plateas de fundación', 'descripcion': 'Hormigonar platea armada como fundación general', 'horas': 24, 'si_aplica': True},
        {'nombre': 'Vigas de fundación', 'descripcion': 'Armar y hormigonar vigas de arriostramiento', 'horas': 16},
        {'nombre': 'Cabezales de pilotes', 'descripcion': 'Hormigonar cabezales sobre pilotes perforados', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Anclajes provisorios', 'descripcion': 'Instalar anclajes temporarios en excavaciones', 'horas': 8, 'si_aplica': True},
    ],

    'Estructura': [
        # --- Tareas originales ---
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
        {'nombre': 'Nivelación final de losas', 'descripcion': 'Nivelación y alisado final de losas', 'horas': 12},
        # --- Tareas nuevas ---
        {'nombre': 'Tabiques de hormigón armado', 'descripcion': 'Armar y hormigonar tabiques portantes de H°A°', 'horas': 20, 'si_aplica': True},
        {'nombre': 'Control de juntas de hormigonado', 'descripcion': 'Verificar y tratar juntas frías entre etapas', 'horas': 4},
        {'nombre': 'Despiece por piso / sector', 'descripcion': 'Planificar y ejecutar hormigonado por sectores', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Hormigonado de tanque de reserva', 'descripcion': 'Armar y hormigonar tanque de agua en azotea', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Hormigonado de rampas', 'descripcion': 'Ejecutar rampas vehiculares o peatonales en H°A°', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Ménsulas y voladizos', 'descripcion': 'Armar y hormigonar elementos en voladizo', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Pretiles y antepechos de H°A°', 'descripcion': 'Hormigonar pretiles perimetrales en azoteas', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Estructura metálica complementaria', 'descripcion': 'Montar vigas o columnas de acero según proyecto', 'horas': 16, 'si_aplica': True},
    ],

    'Mampostería': [
        # --- Tareas originales ---
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
        {'nombre': 'Protección temporal', 'descripcion': 'Protección de muros nuevos contra intemperie', 'horas': 2},
        # --- Tareas nuevas ---
        {'nombre': 'Mampostería de bloques de hormigón', 'descripcion': 'Levantar muros con bloques portantes o no portantes', 'horas': 20, 'si_aplica': True},
        {'nombre': 'Mampostería de HCCA (Retak/Hebel)', 'descripcion': 'Levantar muros con bloques celulares autoclavados', 'horas': 18, 'si_aplica': True},
        {'nombre': 'Encadenados horizontales', 'descripcion': 'Armar y hormigonar encadenados en coronamiento', 'horas': 10},
        {'nombre': 'Columnetas de refuerzo', 'descripcion': 'Hormigonar columnetas dentro de la mampostería', 'horas': 8},
        {'nombre': 'Rozas para instalaciones eléctricas', 'descripcion': 'Ejecutar canales en muros para cañerías eléctricas', 'horas': 8},
        {'nombre': 'Rozas para instalaciones sanitarias', 'descripcion': 'Ejecutar canales en muros para cañerías de agua/gas', 'horas': 6},
        {'nombre': 'Canalización completa', 'descripcion': 'Embutir caños y rellenar rozas con mortero', 'horas': 6},
        {'nombre': 'Mochetas y jambas', 'descripcion': 'Ejecutar terminaciones laterales de aberturas', 'horas': 6},
        {'nombre': 'Mampostería de medianera', 'descripcion': 'Levantar muros medianeros según reglamento', 'horas': 20, 'si_aplica': True},
    ],

    'Techos': [
        # --- Tareas originales ---
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
        {'nombre': 'Control de calidad cubierta', 'descripcion': 'Verificación final de estanqueidad', 'horas': 2},
        # --- Tareas nuevas ---
        {'nombre': 'Impermeabilización de balcones', 'descripcion': 'Aplicar membrana o tratamiento hidrófugo en balcones', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Azotado hidrófugo en baños superiores', 'descripcion': 'Impermeabilizar losas de baños de pisos superiores', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Babetas y encuentros con muros', 'descripcion': 'Sellar unión entre cubierta y muros perimetrales', 'horas': 4},
        {'nombre': 'Desagües pluviales en azotea', 'descripcion': 'Colocar embudos, canaletas y bajadas pluviales', 'horas': 6},
        {'nombre': 'Junta de dilatación en cubierta', 'descripcion': 'Ejecutar juntas en azoteas extensas', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Cumbrera y caballete', 'descripcion': 'Colocar piezas de cierre en cumbrera del techo', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Lucernarios y claraboyas', 'descripcion': 'Instalar aberturas de iluminación cenital', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Acceso a azotea', 'descripcion': 'Instalar tapa o escotilla de acceso al techo', 'horas': 4, 'si_aplica': True},
    ],

    'Instalaciones Eléctricas': [
        # --- Tareas originales ---
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
        {'nombre': 'Documentación eléctrica', 'descripcion': 'Elaboración de planos finales as-built', 'horas': 2},
        # --- Tareas nuevas ---
        {'nombre': 'Acometida desde red pública', 'descripcion': 'Ejecutar conexión desde poste o cámara a tablero', 'horas': 8},
        {'nombre': 'Tablero general de medidores', 'descripcion': 'Instalar tablero con medidores individuales', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Portero eléctrico / videoportero', 'descripcion': 'Instalar sistema de comunicación con acceso', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Sistema de pararrayos', 'descripcion': 'Instalar sistema de protección contra descargas', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Iluminación de emergencia', 'descripcion': 'Instalar luminarias de emergencia en áreas comunes', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Cableado de TV y datos', 'descripcion': 'Tender cables para televisión e internet por UF', 'horas': 8, 'si_aplica': True},
    ],

    'Instalaciones Sanitarias': [
        # --- Tareas originales ---
        {'nombre': 'Colocación de cañerías de agua', 'descripcion': 'Instalación de cañerías de agua fría y caliente', 'horas': 16},
        {'nombre': 'Instalación de desagües', 'descripcion': 'Colocación de cañerías de desagües cloacales y pluviales', 'horas': 12},
        {'nombre': 'Colocación de sanitarios', 'descripcion': 'Instalación de inodoros, bidés y lavatorios', 'horas': 8},
        {'nombre': 'Prueba de estanqueidad', 'descripcion': 'Pruebas de presión y hermeticidad del sistema', 'horas': 4},
        {'nombre': 'Instalación de grifería', 'descripcion': 'Colocación de canillas, duchas y accesorios', 'horas': 6},
        {'nombre': 'Conexión a red cloacal', 'descripcion': 'Conexión final a la red cloacal municipal', 'horas': 4},
        {'nombre': 'Sellado e impermeabilización', 'descripcion': 'Sellado de juntas y puntos críticos', 'horas': 6},
        # --- Tareas nuevas ---
        {'nombre': 'Acometida de agua desde red', 'descripcion': 'Conectar a la red pública con medidor', 'horas': 6},
        {'nombre': 'Tanque de reserva y bombeo', 'descripcion': 'Instalar cisterna, bombas y tanque superior', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Red de incendio', 'descripcion': 'Instalar cañería, gabinetes y boca de impulsión', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Desagüe pluvial', 'descripcion': 'Instalar cañerías y embudo de bajadas pluviales', 'horas': 8},
        {'nombre': 'Ventilación de desagües', 'descripcion': 'Instalar caños de ventilación hasta techo', 'horas': 4},
        {'nombre': 'Cámara de inspección', 'descripcion': 'Construir cámaras de acceso a la red cloacal', 'horas': 6},
        {'nombre': 'Pileta de patio y boca de acceso', 'descripcion': 'Instalar piletas de patio con rejilla', 'horas': 4},
        {'nombre': 'Termotanque / calefón', 'descripcion': 'Instalar equipo de calentamiento de agua', 'horas': 4},
    ],

    'Instalaciones de Gas': [
        # --- Tareas originales ---
        {'nombre': 'Colocación de cañerías principales', 'descripcion': 'Tendido de cañería principal de gas natural', 'horas': 12},
        {'nombre': 'Instalación de llaves de paso', 'descripcion': 'Colocación de llaves de corte y seguridad', 'horas': 4},
        {'nombre': 'Prueba de hermeticidad', 'descripcion': 'Pruebas de presión y detección de fugas', 'horas': 6},
        {'nombre': 'Conexión de artefactos', 'descripcion': 'Conexión final de cocinas, calefones y calderas', 'horas': 8},
        {'nombre': 'Instalación de medidor', 'descripcion': 'Colocación del medidor de gas', 'horas': 2},
        {'nombre': 'Habilitación con empresa gasífera', 'descripcion': 'Trámites y habilitación oficial', 'horas': 4},
        {'nombre': 'Verificación de ventilaciones', 'descripcion': 'Control de ventilaciones según normativa', 'horas': 2},
        # --- Tareas nuevas ---
        {'nombre': 'Gabinete de medidores', 'descripcion': 'Instalar gabinete con medidores individuales', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Cañería troncal (columna)', 'descripcion': 'Instalar cañería de distribución vertical', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Rejillas de ventilación reglamentarias', 'descripcion': 'Colocar rejillas alta y baja según norma', 'horas': 4},
        {'nombre': 'Detector de gas', 'descripcion': 'Instalar detector de monóxido de carbono', 'horas': 2, 'si_aplica': True},
        {'nombre': 'Caldera y calefacción central', 'descripcion': 'Instalar sistema de calefacción centralizada', 'horas': 24, 'si_aplica': True},
    ],

    'Revoque Grueso': [
        # --- Tareas originales ---
        {'nombre': 'Preparación de mezcla gruesa', 'descripcion': 'Preparación de mortero para revoque base', 'horas': 2},
        {'nombre': 'Aplicación de capa base', 'descripcion': 'Aplicación de primera capa de revoque grueso', 'horas': 20},
        {'nombre': 'Nivelado de superficie', 'descripcion': 'Nivelación y alisado de superficies', 'horas': 16},
        {'nombre': 'Curado y preparación para capa fina', 'descripcion': 'Curado del revoque y preparación para terminación', 'horas': 8},
        {'nombre': 'Aplicación revoque grueso exterior', 'descripcion': 'Revoque grueso en paredes exteriores', 'horas': 24},
        {'nombre': 'Aplicación revoque grueso interior', 'descripcion': 'Revoque grueso en paredes interiores', 'horas': 16},
        {'nombre': 'Verificación de verticalidad', 'descripcion': 'Control de plomadas y niveles', 'horas': 4},
        # --- Tareas nuevas ---
        {'nombre': 'Jaharro cementicio', 'descripcion': 'Aplicar capa de adherencia previa al revoque', 'horas': 8},
        {'nombre': 'Revoque hidrófugo en muros húmedos', 'descripcion': 'Aplicar revoque con aditivo hidrófugo en baños/cocina', 'horas': 10},
        {'nombre': 'Revoque sobre hormigón visto', 'descripcion': 'Aplicar azotado y revoque sobre superficies de H°A°', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Fajas maestras', 'descripcion': 'Ejecutar guías verticales de nivel para revocar', 'horas': 6},
        {'nombre': 'Revoque en cielorrasos', 'descripcion': 'Aplicar revoque grueso bajo losas', 'horas': 12, 'si_aplica': True},
    ],

    'Revoque Fino': [
        # --- Tareas originales ---
        {'nombre': 'Preparación de mezcla', 'descripcion': 'Preparación de mortero fino para terminación', 'horas': 2},
        {'nombre': 'Aplicación de capa fina', 'descripcion': 'Aplicación de revoque fino sobre base', 'horas': 18},
        {'nombre': 'Nivelado y alisado', 'descripcion': 'Nivelación perfecta y alisado final', 'horas': 12},
        {'nombre': 'Curado y protección', 'descripcion': 'Curado controlado del revoque fino', 'horas': 6},
        {'nombre': 'Aplicación interior', 'descripcion': 'Revoque fino en ambientes interiores', 'horas': 16},
        {'nombre': 'Aplicación exterior', 'descripcion': 'Revoque fino en fachadas', 'horas': 20},
        {'nombre': 'Preparación para pintura', 'descripcion': 'Lijado y preparación final', 'horas': 8},
        # --- Tareas nuevas ---
        {'nombre': 'Enlucido fino interior', 'descripcion': 'Aplicar terminación lisa lista para pintura', 'horas': 14},
        {'nombre': 'Revoque fino exterior texturado', 'descripcion': 'Aplicar terminación texturada en fachadas', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Fratachado mecánico', 'descripcion': 'Alisar superficie con fratachadora mecánica', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Reparación de imperfecciones', 'descripcion': 'Emparchar y corregir irregularidades antes de pintar', 'horas': 6},
    ],

    'Pisos': [
        # --- Tareas originales ---
        {'nombre': 'Preparación de superficie', 'descripcion': 'Preparación y nivelación de contrapisos', 'horas': 12},
        {'nombre': 'Colocación de baldosas o parquet', 'descripcion': 'Instalación del piso definitivo', 'horas': 24},
        {'nombre': 'Aplicación de fragüe o sellador', 'descripcion': 'Fragüe de juntas y sellado', 'horas': 8},
        {'nombre': 'Pulido y limpieza final', 'descripcion': 'Pulido y limpieza final de pisos', 'horas': 6},
        {'nombre': 'Colocación de pisos cerámicos', 'descripcion': 'Instalación de cerámicos y porcelanatos', 'horas': 20},
        {'nombre': 'Colocación de pisos de madera', 'descripcion': 'Instalación de parquet o deck', 'horas': 18},
        {'nombre': 'Instalación de zócalos', 'descripcion': 'Colocación de zócalos perimetrales', 'horas': 8},
        # --- Tareas nuevas ---
        {'nombre': 'Pavimento de hormigón llaneado', 'descripcion': 'Ejecutar piso industrial de hormigón', 'horas': 20, 'si_aplica': True},
        {'nombre': 'Juntas de dilatación en pisos', 'descripcion': 'Cortar juntas de contracción en pavimentos', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Canaletas de desagüe en pisos', 'descripcion': 'Colocar canaletas lineales en cocheras/lavaderos', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Veredas perimetrales', 'descripcion': 'Ejecutar veredas de hormigón en perímetro del edificio', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Porcellanato en áreas comunes', 'descripcion': 'Colocar porcellanato en hall, palier y pasillos', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Porcellanato en unidades funcionales', 'descripcion': 'Colocar porcellanato en ambientes de departamentos', 'horas': 20, 'si_aplica': True},
        {'nombre': 'Pisos de deck (exterior)', 'descripcion': 'Colocar deck de madera o WPC en terrazas', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Umbrales y solías de piso', 'descripcion': 'Colocar piezas de transición entre ambientes', 'horas': 4},
        {'nombre': 'Alisado y pulido de mosaicos', 'descripcion': 'Pulir y lustrar pisos de mosaico granítico', 'horas': 12, 'si_aplica': True},
    ],

    'Carpintería': [
        # --- Tareas originales ---
        {'nombre': 'Medición y corte de piezas', 'descripcion': 'Medición y corte preciso de maderas', 'horas': 8},
        {'nombre': 'Ensamblado de estructuras', 'descripcion': 'Armado y ensamblado de marcos', 'horas': 12},
        {'nombre': 'Colocación de puertas y ventanas', 'descripcion': 'Instalación final de aberturas', 'horas': 16},
        {'nombre': 'Barnizado o pintado de madera', 'descripcion': 'Acabado final de carpintería', 'horas': 10},
        {'nombre': 'Instalación de marcos', 'descripcion': 'Colocación de marcos de puertas y ventanas', 'horas': 12},
        {'nombre': 'Instalación de herrajes', 'descripcion': 'Colocación de bisagras, cerraduras y manijas', 'horas': 6},
        {'nombre': 'Ajuste y regulación', 'descripcion': 'Ajuste final y regulación de aberturas', 'horas': 4},
        # --- Tareas nuevas ---
        {'nombre': 'Carpintería de aluminio', 'descripcion': 'Instalar ventanas y puertas de aluminio', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Carpintería de PVC', 'descripcion': 'Instalar aberturas de PVC con DVH', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Puertas placa interiores', 'descripcion': 'Colocar puertas placa con marco de chapa', 'horas': 12},
        {'nombre': 'Puerta de entrada blindada', 'descripcion': 'Instalar puerta de seguridad en acceso principal', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Portón de garage', 'descripcion': 'Instalar portón corredizo o levadizo', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Mampara de ducha', 'descripcion': 'Instalar mampara de vidrio templado', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Placard y vestidor', 'descripcion': 'Instalar frentes de placard e interiores', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Muebles de cocina', 'descripcion': 'Instalar muebles bajo y sobre mesada', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Guardacantos metálicos', 'descripcion': 'Colocar perfiles de protección en aristas vivas', 'horas': 4},
        {'nombre': 'Flejes y solías de carpintería', 'descripcion': 'Instalar flejes de goteo y solías de aluminio', 'horas': 4},
    ],

    'Pintura': [
        # --- Tareas originales ---
        {'nombre': 'Lijado de superficies', 'descripcion': 'Lijado y preparación de superficies a pintar', 'horas': 8},
        {'nombre': 'Aplicación de sellador', 'descripcion': 'Aplicación de sellador y fijador', 'horas': 6},
        {'nombre': 'Primera mano de pintura', 'descripcion': 'Aplicación de la primera mano de pintura', 'horas': 12},
        {'nombre': 'Segunda mano de pintura', 'descripcion': 'Aplicación de mano final de pintura', 'horas': 10},
        {'nombre': 'Revisión y retoques finales', 'descripcion': 'Inspección final y corrección de detalles', 'horas': 6},
        {'nombre': 'Pintura interior', 'descripcion': 'Pintura completa de ambientes interiores', 'horas': 16},
        {'nombre': 'Pintura exterior', 'descripcion': 'Pintura de fachadas y exteriores', 'horas': 20},
        # --- Tareas nuevas ---
        {'nombre': 'Enduido de paredes', 'descripcion': 'Aplicar enduido plástico para emparejar superficies', 'horas': 12},
        {'nombre': 'Pintura epoxi en pisos', 'descripcion': 'Aplicar pintura epoxi en cocheras o depósitos', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Pintura de medianeras', 'descripcion': 'Pintar muros medianeros con revestimiento exterior', 'horas': 12},
        {'nombre': 'Pintura de rejas y herrería', 'descripcion': 'Lijar, aplicar antióxido y esmaltar rejas', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Pintura de cielorrasos', 'descripcion': 'Aplicar pintura en cielos rasos interiores', 'horas': 10},
        {'nombre': 'Retoques post-mudanza', 'descripcion': 'Reparar y retocar marcas previas a la entrega', 'horas': 6},
    ],

    'Instalaciones Complementarias': [
        # --- Tareas originales ---
        {'nombre': 'Instalación de aire acondicionado', 'descripcion': 'Montaje de equipos de climatización', 'horas': 12},
        {'nombre': 'Instalación de calefacción', 'descripcion': 'Sistema de calefacción central o individual', 'horas': 16},
        {'nombre': 'Instalación de sistema de seguridad', 'descripcion': 'Alarmas, cámaras y sistemas de monitoreo', 'horas': 10},
        {'nombre': 'Instalación de portones automáticos', 'descripcion': 'Automatización de portones y accesos', 'horas': 8},
        {'nombre': 'Colocación de toldos', 'descripcion': 'Instalación de toldos y protecciones solares', 'horas': 6},
        {'nombre': 'Instalación de sistema de riego', 'descripcion': 'Sistema de riego automático para jardines', 'horas': 12},
        {'nombre': 'Configuración domótica', 'descripcion': 'Programación de sistemas inteligentes', 'horas': 8},
        # --- Tareas nuevas ---
        {'nombre': 'Ascensor / montacargas', 'descripcion': 'Instalar cabina, guías y sala de máquinas', 'horas': 40, 'si_aplica': True},
        {'nombre': 'Sistema de bombeo cloacal', 'descripcion': 'Instalar bomba para desagüe en subsuelos', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Presurización de escaleras', 'descripcion': 'Instalar ventiladores de presurización contra incendio', 'horas': 16, 'si_aplica': True},
        {'nombre': 'Grupo electrógeno', 'descripcion': 'Instalar generador de emergencia', 'horas': 12, 'si_aplica': True},
        {'nombre': 'Topes de estacionamiento', 'descripcion': 'Colocar topes de hormigón o goma en cocheras', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Señalización interna', 'descripcion': 'Colocar cartelería de emergencia y señalización', 'horas': 4, 'si_aplica': True},
        {'nombre': 'Cerrajería y control de acceso', 'descripcion': 'Instalar sistema de acceso con llave, tarjeta o código', 'horas': 8, 'si_aplica': True},
    ],

    'Limpieza Final': [
        # --- Tareas originales ---
        {'nombre': 'Limpieza de obra gruesa', 'descripcion': 'Limpieza general y retiro de escombros', 'horas': 12},
        {'nombre': 'Limpieza de vidrios', 'descripcion': 'Limpieza de todas las superficies vidriadas', 'horas': 6},
        {'nombre': 'Limpieza de pisos y superficies', 'descripcion': 'Limpieza profunda de pisos y superficies', 'horas': 8},
        {'nombre': 'Retiro de material sobrante', 'descripcion': 'Retiro final de materiales y herramientas', 'horas': 4},
        {'nombre': 'Limpieza de instalaciones', 'descripcion': 'Limpieza de sanitarios y instalaciones', 'horas': 4},
        {'nombre': 'Entrega de documentación', 'descripcion': 'Preparación de documentación de entrega', 'horas': 2},
        {'nombre': 'Inspección final', 'descripcion': 'Inspección final y lista de pendientes', 'horas': 4},
        # --- Tareas nuevas ---
        {'nombre': 'Destapación de cañerías', 'descripcion': 'Verificar y destapar cañerías obstruidas por obra', 'horas': 4},
        {'nombre': 'Limpieza de unidades funcionales', 'descripcion': 'Limpiar cada departamento o local individualmente', 'horas': 8, 'si_aplica': True},
        {'nombre': 'Limpieza de áreas comunes', 'descripcion': 'Limpiar hall, escaleras, pasillos y ascensor', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Limpieza de tanques de agua', 'descripcion': 'Lavar y desinfectar cisterna y tanque superior', 'horas': 4},
        {'nombre': 'Retiro del obrador', 'descripcion': 'Desmontar obrador, cerco y servicios provisorios', 'horas': 8},
        {'nombre': 'Reparación de veredas públicas', 'descripcion': 'Reparar daños causados por la obra en vereda', 'horas': 6, 'si_aplica': True},
        {'nombre': 'Checklist de entrega final', 'descripcion': 'Verificar terminaciones y funcionamiento general', 'horas': 4},
        {'nombre': 'Confección de manual de usuario', 'descripcion': 'Entregar manual con instrucciones de uso y garantías', 'horas': 4, 'si_aplica': True},
    ],
}

def obtener_tareas_por_etapa(nombre_etapa=None, slug: str | None = None):
    """Obtiene tareas predefinidas tolerando variaciones en el nombre."""

    if nombre_etapa:
        nombre_etapa = nombre_etapa.strip()
        if nombre_etapa in TAREAS_POR_ETAPA:
            return TAREAS_POR_ETAPA[nombre_etapa]

        capitalizada = nombre_etapa.title()
        if capitalizada in TAREAS_POR_ETAPA:
            return TAREAS_POR_ETAPA[capitalizada]

        slug = slug or _slugify_etapa(nombre_etapa)

    if slug:
        slug_normalizado = _slugify_etapa(slug)
        for nombre, tareas in TAREAS_POR_ETAPA.items():
            if _slugify_etapa(nombre) == slug_normalizado:
                return tareas

    return []


def obtener_todas_las_etapas_con_tareas():
    """Retorna todas las etapas con sus tareas asociadas"""
    return TAREAS_POR_ETAPA


def slugify_nombre_etapa(nombre: str) -> str:
    return _slugify_etapa(nombre)
