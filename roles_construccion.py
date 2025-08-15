# roles_construccion.py
# Definición completa de roles de construcción para OBYRA IA

ROLES_CONSTRUCCION = {
    # Dirección y gestión
    'director_general': 'Director General / Gerente General',
    'director_operaciones': 'Director de Operaciones',
    'director_proyectos': 'Director de Proyectos',
    'jefe_obra': 'Jefe de Obra (Project Manager)',
    'jefe_produccion': 'Jefe de Producción',
    'coordinador_proyectos': 'Coordinador de Proyectos',
    'encargado_obra': 'Encargado de Obra',
    
    # Técnico-ingeniería
    'ingeniero_civil': 'Ingeniero Civil',
    'ingeniero_construcciones': 'Ingeniero en Construcciones',
    'arquitecto': 'Arquitecto / Diseñador',
    'ingeniero_seguridad': 'Ingeniero en Seguridad e Higiene',
    'ingeniero_electrico': 'Ingeniero Eléctrico',
    'ingeniero_sanitario': 'Ingeniero Sanitario',
    'ingeniero_mecanico': 'Ingeniero Mecánico',
    'topografo': 'Topógrafo',
    'bim_manager': 'BIM Manager / Modelador BIM',
    'computo_presupuesto': 'Cómputo y Presupuesto',
    
    # Supervisión y control
    'supervisor_obra': 'Supervisor de Obra',
    'inspector_calidad': 'Inspector de Calidad',
    'inspector_seguridad': 'Inspector de Seguridad',
    'supervisor_especialidades': 'Supervisor de Especialidades',
    
    # Administración y soporte
    'administrador_obra': 'Administrador de Obra',
    'comprador': 'Comprador / Abastecimiento',
    'logistica': 'Logística y Transporte',
    'recursos_humanos': 'Recursos Humanos (en obra)',
    'contador_finanzas': 'Contador / Finanzas',
    
    # Operativo en terreno
    'capataz': 'Capataz',
    'maestro_mayor_obra': 'Maestro Mayor de Obra',
    'oficial_albanil': 'Oficial Albañil',
    'oficial_plomero': 'Oficial Plomero',
    'oficial_electricista': 'Oficial Electricista',
    'oficial_herrero': 'Oficial Herrero',
    'oficial_pintor': 'Oficial Pintor',
    'oficial_yesero': 'Oficial Yesero',
    'medio_oficial': 'Medio Oficial',
    'ayudante': 'Ayudante',
    'operador_maquinaria': 'Operador de Maquinaria Pesada',
    'chofer_camion': 'Chofer de Camión',
    
    # Mantener compatibilidad con roles anteriores
    'administrador': 'Administrador del Sistema',
    'tecnico': 'Técnico General',
    'operario': 'Operario General'
}

# Categorías de roles para organización en formularios
CATEGORIAS_ROLES = {
    'Dirección y Gestión': [
        'director_general', 'director_operaciones', 'director_proyectos',
        'jefe_obra', 'jefe_produccion', 'coordinador_proyectos', 'encargado_obra'
    ],
    'Técnico-Ingeniería': [
        'ingeniero_civil', 'ingeniero_construcciones', 'arquitecto',
        'ingeniero_seguridad', 'ingeniero_electrico', 'ingeniero_sanitario',
        'ingeniero_mecanico', 'topografo', 'bim_manager', 'computo_presupuesto'
    ],
    'Supervisión y Control': [
        'supervisor_obra', 'inspector_calidad', 'inspector_seguridad',
        'supervisor_especialidades'
    ],
    'Administración y Soporte': [
        'administrador_obra', 'comprador', 'logistica',
        'recursos_humanos', 'contador_finanzas'
    ],
    'Operativo en Terreno': [
        'capataz', 'maestro_mayor_obra', 'oficial_albanil', 'oficial_plomero',
        'oficial_electricista', 'oficial_herrero', 'oficial_pintor', 'oficial_yesero',
        'medio_oficial', 'ayudante', 'operador_maquinaria', 'chofer_camion'
    ],
    'Roles del Sistema': [
        'administrador', 'tecnico', 'operario'
    ]
}

def obtener_roles_por_categoria():
    """Retorna los roles organizados por categoría para uso en formularios"""
    return CATEGORIAS_ROLES

def obtener_nombre_rol(codigo_rol):
    """Retorna el nombre completo de un rol dado su código"""
    return ROLES_CONSTRUCCION.get(codigo_rol, codigo_rol.title())

def es_rol_direccion(rol):
    """Verifica si un rol pertenece a la categoría de dirección"""
    return rol in CATEGORIAS_ROLES['Dirección y Gestión']

def es_rol_tecnico(rol):
    """Verifica si un rol pertenece a la categoría técnica"""
    return rol in CATEGORIAS_ROLES['Técnico-Ingeniería']

def es_rol_supervision(rol):
    """Verifica si un rol pertenece a la categoría de supervisión"""
    return rol in CATEGORIAS_ROLES['Supervisión y Control']

def es_rol_administrativo(rol):
    """Verifica si un rol pertenece a la categoría administrativa"""
    return rol in CATEGORIAS_ROLES['Administración y Soporte']

def es_rol_operativo(rol):
    """Verifica si un rol pertenece a la categoría operativa"""
    return rol in CATEGORIAS_ROLES['Operativo en Terreno']

def obtener_nivel_jerarquico(rol):
    """Retorna el nivel jerárquico del rol (1=más alto, 5=más bajo)"""
    if es_rol_direccion(rol):
        return 1
    elif es_rol_tecnico(rol):
        return 2
    elif es_rol_supervision(rol):
        return 3
    elif es_rol_administrativo(rol):
        return 3
    elif es_rol_operativo(rol):
        return 4
    else:
        return 5  # Roles del sistema