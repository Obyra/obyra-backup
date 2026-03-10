"""
Índices de construcción reales para edificios en Argentina.

Ratios por sección de edificio (subsuelo, PB, planta tipo, terraza)
y por rubro, cada uno en su unidad natural:
  - Hormigón: m³
  - Hierro/Acero: kg
  - Encofrado: m²
  - Albañilería/Mampostería: m²
  - Revoque: m²
  - Contrapiso: m²
  - Carpeta: m²
  - Pisos/Revestimientos: m²
  - Pintura: m²
  - Inst. Eléctrica: puntos
  - Inst. Sanitaria: puntos
  - Inst. Gas: puntos
  - Carpintería: m²

Todos los ratios son POR m² CUBIERTO de esa sección.
Fuente: promedios de obra real en CABA/GBA, construcción tradicional.
"""

# ---------------------------------------------------------------------------
# Ratios de consumo por m² cubierto, según sección del edificio
# ---------------------------------------------------------------------------
# Cada valor indica cuántas unidades del rubro se necesitan por cada m²
# cubierto de esa sección.
#
# Ejemplo: subsuelo → hormigon_m3: 0.55 significa que por cada m² de
# subsuelo se necesitan 0.55 m³ de hormigón.
# ---------------------------------------------------------------------------

SECCIONES_EDIFICIO = {
    'subsuelo': {
        'nombre': 'Subsuelo',
        'descripcion': 'Incluye fundaciones, muros de contención, losa de subpresión',
        'rubros': {
            'hormigon': {
                'unidad': 'm³',
                'ratio_por_m2': 0.55,
                'detalle': 'Plateas, muros, columnas, vigas, losa',
                'rango': (0.45, 0.70),
            },
            'acero': {
                'unidad': 'kg',
                'ratio_por_m2': 55.0,
                'detalle': 'Aprox 100 kg/m³ de hormigón',
                'rango': (45.0, 70.0),
            },
            'encofrado': {
                'unidad': 'm²',
                'ratio_por_m2': 3.5,
                'detalle': 'Encofrado de muros, columnas, vigas, losas',
                'rango': (2.8, 4.5),
            },
            'mamposteria': {
                'unidad': 'm²',
                'ratio_por_m2': 0.3,
                'detalle': 'Mínima: tabiques de instalaciones',
                'rango': (0.1, 0.5),
            },
            'impermeabilizacion': {
                'unidad': 'm²',
                'ratio_por_m2': 2.0,
                'detalle': 'Muros y losa en contacto con suelo',
                'rango': (1.5, 2.5),
            },
        },
    },

    'planta_baja': {
        'nombre': 'Planta Baja',
        'descripcion': 'Hall, locales, cocheras o vivienda según proyecto',
        'rubros': {
            'hormigon': {
                'unidad': 'm³',
                'ratio_por_m2': 0.30,
                'detalle': 'Columnas, vigas, losa',
                'rango': (0.22, 0.38),
            },
            'acero': {
                'unidad': 'kg',
                'ratio_por_m2': 30.0,
                'detalle': 'Aprox 100 kg/m³ de hormigón',
                'rango': (22.0, 38.0),
            },
            'encofrado': {
                'unidad': 'm²',
                'ratio_por_m2': 2.2,
                'detalle': 'Columnas, vigas, losa',
                'rango': (1.8, 3.0),
            },
            'mamposteria': {
                'unidad': 'm²',
                'ratio_por_m2': 1.4,
                'detalle': 'Cerramientos exteriores + divisorios interiores',
                'rango': (1.0, 1.8),
            },
            'revoque': {
                'unidad': 'm²',
                'ratio_por_m2': 2.8,
                'detalle': 'Ambas caras de muros (grueso + fino)',
                'rango': (2.2, 3.5),
            },
            'contrapiso': {
                'unidad': 'm²',
                'ratio_por_m2': 1.0,
                'detalle': 'Toda la superficie de piso',
                'rango': (0.95, 1.05),
            },
            'pisos': {
                'unidad': 'm²',
                'ratio_por_m2': 1.05,
                'detalle': 'Superficie + 5% desperdicio',
                'rango': (1.0, 1.10),
            },
            'pintura': {
                'unidad': 'm²',
                'ratio_por_m2': 2.5,
                'detalle': 'Paredes + cielorrasos (2 manos)',
                'rango': (2.0, 3.0),
            },
            'inst_electrica': {
                'unidad': 'puntos',
                'ratio_por_m2': 0.25,
                'detalle': '1 punto cada 4 m² aprox',
                'rango': (0.18, 0.35),
            },
            'inst_sanitaria': {
                'unidad': 'puntos',
                'ratio_por_m2': 0.04,
                'detalle': 'Baños y cocinas',
                'rango': (0.02, 0.08),
            },
            'carpinteria': {
                'unidad': 'm²',
                'ratio_por_m2': 0.10,
                'detalle': 'Puertas y ventanas',
                'rango': (0.06, 0.15),
            },
        },
    },

    'planta_tipo': {
        'nombre': 'Planta Tipo',
        'descripcion': 'Piso repetitivo de departamentos/oficinas',
        'rubros': {
            'hormigon': {
                'unidad': 'm³',
                'ratio_por_m2': 0.25,
                'detalle': 'Columnas, vigas, losa (menos que PB)',
                'rango': (0.18, 0.32),
            },
            'acero': {
                'unidad': 'kg',
                'ratio_por_m2': 25.0,
                'detalle': 'Aprox 100 kg/m³ de hormigón',
                'rango': (18.0, 35.0),
            },
            'encofrado': {
                'unidad': 'm²',
                'ratio_por_m2': 2.0,
                'detalle': 'Reutilizable en plantas tipo',
                'rango': (1.5, 2.5),
            },
            'mamposteria': {
                'unidad': 'm²',
                'ratio_por_m2': 1.5,
                'detalle': 'Más divisorios internos que PB',
                'rango': (1.2, 2.0),
            },
            'revoque': {
                'unidad': 'm²',
                'ratio_por_m2': 3.0,
                'detalle': 'Ambas caras de muros',
                'rango': (2.4, 3.8),
            },
            'contrapiso': {
                'unidad': 'm²',
                'ratio_por_m2': 1.0,
                'detalle': 'Toda la superficie',
                'rango': (0.95, 1.05),
            },
            'pisos': {
                'unidad': 'm²',
                'ratio_por_m2': 1.05,
                'detalle': 'Superficie + desperdicio',
                'rango': (1.0, 1.10),
            },
            'revestimientos': {
                'unidad': 'm²',
                'ratio_por_m2': 0.25,
                'detalle': 'Cerámicos en baños y cocinas',
                'rango': (0.15, 0.40),
            },
            'pintura': {
                'unidad': 'm²',
                'ratio_por_m2': 2.8,
                'detalle': 'Paredes + cielorrasos',
                'rango': (2.2, 3.5),
            },
            'inst_electrica': {
                'unidad': 'puntos',
                'ratio_por_m2': 0.28,
                'detalle': '1 punto cada 3.5 m² aprox',
                'rango': (0.20, 0.40),
            },
            'inst_sanitaria': {
                'unidad': 'puntos',
                'ratio_por_m2': 0.05,
                'detalle': 'Baños y cocina por depto',
                'rango': (0.03, 0.10),
            },
            'inst_gas': {
                'unidad': 'puntos',
                'ratio_por_m2': 0.02,
                'detalle': 'Cocina y calefón por depto',
                'rango': (0.01, 0.04),
            },
            'carpinteria': {
                'unidad': 'm²',
                'ratio_por_m2': 0.12,
                'detalle': 'Puertas interiores + ventanas',
                'rango': (0.08, 0.18),
            },
            'cielorrasos': {
                'unidad': 'm²',
                'ratio_por_m2': 1.0,
                'detalle': 'Aplicado o suspendido',
                'rango': (0.9, 1.05),
            },
        },
    },

    'terraza': {
        'nombre': 'Terraza / Azotea',
        'descripcion': 'Losa de terraza, parapetos, impermeabilización, sala de máquinas',
        'rubros': {
            'hormigon': {
                'unidad': 'm³',
                'ratio_por_m2': 0.28,
                'detalle': 'Losa + parapetos + sala de máquinas',
                'rango': (0.20, 0.35),
            },
            'acero': {
                'unidad': 'kg',
                'ratio_por_m2': 28.0,
                'detalle': 'Losa + parapetos',
                'rango': (20.0, 38.0),
            },
            'encofrado': {
                'unidad': 'm²',
                'ratio_por_m2': 1.8,
                'detalle': 'Losa y parapetos',
                'rango': (1.2, 2.5),
            },
            'impermeabilizacion': {
                'unidad': 'm²',
                'ratio_por_m2': 1.15,
                'detalle': 'Membrana asfáltica/poliuretánica',
                'rango': (1.05, 1.30),
            },
            'contrapiso': {
                'unidad': 'm²',
                'ratio_por_m2': 1.0,
                'detalle': 'Con pendiente para desagüe',
                'rango': (0.95, 1.05),
            },
            'pintura': {
                'unidad': 'm²',
                'ratio_por_m2': 0.8,
                'detalle': 'Parapetos y sala de máquinas',
                'rango': (0.5, 1.2),
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Ratio hierro/hormigón por elemento estructural (kg de acero por m³ H°A°)
# ---------------------------------------------------------------------------
RATIO_ACERO_POR_M3_HORMIGON = {
    'fundaciones':  {'ratio': 70,  'rango': (55, 90),   'unidad': 'kg/m³'},
    'columnas':     {'ratio': 135, 'rango': (110, 160),  'unidad': 'kg/m³'},
    'vigas':        {'ratio': 115, 'rango': (90, 140),   'unidad': 'kg/m³'},
    'losas':        {'ratio': 85,  'rango': (70, 110),   'unidad': 'kg/m³'},
    'muros':        {'ratio': 75,  'rango': (60, 95),    'unidad': 'kg/m³'},
    'escaleras':    {'ratio': 100, 'rango': (80, 120),   'unidad': 'kg/m³'},
    'tanque_agua':  {'ratio': 110, 'rango': (90, 130),   'unidad': 'kg/m³'},
    'promedio_general': {'ratio': 100, 'rango': (80, 120), 'unidad': 'kg/m³'},
}


# ---------------------------------------------------------------------------
# Unidades naturales por rubro (para mostrar en reportes)
# ---------------------------------------------------------------------------
UNIDAD_POR_RUBRO = {
    'hormigon':             'm³',
    'acero':                'kg',
    'encofrado':            'm²',
    'mamposteria':          'm²',
    'revoque':              'm²',
    'contrapiso':           'm²',
    'pisos':                'm²',
    'revestimientos':       'm²',
    'pintura':              'm²',
    'cielorrasos':          'm²',
    'impermeabilizacion':   'm²',
    'carpinteria':          'm²',
    'inst_electrica':       'puntos',
    'inst_sanitaria':       'puntos',
    'inst_gas':             'puntos',
}


# ---------------------------------------------------------------------------
# Mapeo de categorías de inventario / etapas → rubro de índice
# ---------------------------------------------------------------------------
# Sirve para vincular items del inventario o etapas de obra con el rubro
# correspondiente en los índices, permitiendo calcular consumo real vs teórico.
MAPEO_CATEGORIA_A_RUBRO = {
    # Categorías de inventario
    'hormigon':         'hormigon',
    'hormigón':         'hormigon',
    'cemento':          'hormigon',
    'hierro':           'acero',
    'acero':            'acero',
    'alambre':          'acero',
    'encofrado':        'encofrado',
    'madera':           'encofrado',
    'fenolico':         'encofrado',
    'fenólico':         'encofrado',
    'ladrillo':         'mamposteria',
    'ladrillos':        'mamposteria',
    'bloques':          'mamposteria',
    'mamposteria':      'mamposteria',
    'mampostería':      'mamposteria',
    'revoque':          'revoque',
    'arena':            'revoque',
    'cal':              'revoque',
    'contrapiso':       'contrapiso',
    'ceramico':         'pisos',
    'cerámico':         'pisos',
    'ceramica':         'pisos',
    'cerámica':         'pisos',
    'porcelanato':      'pisos',
    'piso':             'pisos',
    'pisos':            'pisos',
    'revestimiento':    'revestimientos',
    'pintura':          'pintura',
    'latex':            'pintura',
    'esmalte':          'pintura',
    'membrana':         'impermeabilizacion',
    'impermeabilizante': 'impermeabilizacion',
    'carpinteria':      'carpinteria',
    'carpintería':      'carpinteria',
    'ventana':          'carpinteria',
    'puerta':           'carpinteria',
    'electrico':        'inst_electrica',
    'eléctrico':        'inst_electrica',
    'cable':            'inst_electrica',
    'sanitario':        'inst_sanitaria',
    'caño':             'inst_sanitaria',
    'cano':             'inst_sanitaria',
    'gas':              'inst_gas',
}

# Mapeo de slugs de etapa → rubro
MAPEO_ETAPA_A_RUBRO = {
    'excavacion':               None,  # no tiene rubro de índice directo
    'fundaciones':              'hormigon',
    'estructura':               'hormigon',
    'mamposteria':              'mamposteria',
    'techos':                   'impermeabilizacion',
    'impermeabilizaciones-aislaciones': 'impermeabilizacion',
    'instalaciones-electricas': 'inst_electrica',
    'instalaciones-sanitarias': 'inst_sanitaria',
    'instalaciones-gas':        'inst_gas',
    'revoque-grueso':           'revoque',
    'revoque-fino':             'revoque',
    'yeseria-enlucidos':        'revoque',
    'contrapisos-carpetas':     'contrapiso',
    'cielorrasos':              'cielorrasos',
    'pisos':                    'pisos',
    'carpinteria':              'carpinteria',
    'pintura':                  'pintura',
    'construccion-en-seco':     'mamposteria',
}


# ---------------------------------------------------------------------------
# Funciones de cálculo
# ---------------------------------------------------------------------------

def calcular_teorico_por_seccion(superficie_m2, seccion='planta_tipo'):
    """
    Dado m² cubiertos de una sección, devuelve las cantidades teóricas
    de cada rubro en su unidad natural.

    Retorna dict: {rubro: {'cantidad': float, 'unidad': str, 'rango': (min, max)}}
    """
    seccion_data = SECCIONES_EDIFICIO.get(seccion)
    if not seccion_data:
        return {}

    resultado = {}
    for rubro, datos in seccion_data['rubros'].items():
        cantidad = round(superficie_m2 * datos['ratio_por_m2'], 2)
        rango_min = round(superficie_m2 * datos['rango'][0], 2)
        rango_max = round(superficie_m2 * datos['rango'][1], 2)
        resultado[rubro] = {
            'cantidad': cantidad,
            'unidad': datos['unidad'],
            'rango': (rango_min, rango_max),
            'detalle': datos['detalle'],
        }
    return resultado


def calcular_teorico_edificio(secciones):
    """
    Calcula consumo teórico total de un edificio con múltiples secciones.

    Args:
        secciones: lista de dicts con:
            - tipo: 'subsuelo', 'planta_baja', 'planta_tipo', 'terraza'
            - superficie_m2: float
            - cantidad: int (ej: 8 plantas tipo)

    Ejemplo:
        secciones = [
            {'tipo': 'subsuelo', 'superficie_m2': 400, 'cantidad': 2},
            {'tipo': 'planta_baja', 'superficie_m2': 350, 'cantidad': 1},
            {'tipo': 'planta_tipo', 'superficie_m2': 300, 'cantidad': 8},
            {'tipo': 'terraza', 'superficie_m2': 300, 'cantidad': 1},
        ]

    Retorna dict con totales por rubro y desglose por sección.
    """
    totales = {}
    desglose = []

    for sec in secciones:
        tipo = sec['tipo']
        sup = sec['superficie_m2']
        cant = sec.get('cantidad', 1)
        sup_total = sup * cant

        teorico = calcular_teorico_por_seccion(sup_total, tipo)

        desglose.append({
            'tipo': tipo,
            'nombre': SECCIONES_EDIFICIO.get(tipo, {}).get('nombre', tipo),
            'superficie_unitaria': sup,
            'cantidad': cant,
            'superficie_total': sup_total,
            'rubros': teorico,
        })

        for rubro, datos in teorico.items():
            if rubro not in totales:
                totales[rubro] = {
                    'cantidad': 0,
                    'unidad': datos['unidad'],
                    'rango_min': 0,
                    'rango_max': 0,
                }
            totales[rubro]['cantidad'] += datos['cantidad']
            totales[rubro]['rango_min'] += datos['rango'][0]
            totales[rubro]['rango_max'] += datos['rango'][1]

    # Redondear totales
    for rubro in totales:
        totales[rubro]['cantidad'] = round(totales[rubro]['cantidad'], 2)
        totales[rubro]['rango_min'] = round(totales[rubro]['rango_min'], 2)
        totales[rubro]['rango_max'] = round(totales[rubro]['rango_max'], 2)

    # Superficie total del edificio
    sup_total_edificio = sum(s['superficie_m2'] * s.get('cantidad', 1) for s in secciones)

    return {
        'superficie_total_m2': sup_total_edificio,
        'totales': totales,
        'desglose': desglose,
    }


def comparar_consumo_real_vs_teorico(consumo_real, consumo_teorico):
    """
    Compara consumo real (de inventario/registros) vs teórico (de índices).

    Args:
        consumo_real: dict {rubro: {'cantidad': float, 'unidad': str, 'costo': float}}
        consumo_teorico: dict {rubro: {'cantidad': float, 'unidad': str}}

    Retorna dict por rubro con desvío, eficiencia y alertas.
    """
    comparacion = {}

    todos_rubros = set(list(consumo_real.keys()) + list(consumo_teorico.keys()))

    for rubro in todos_rubros:
        real = consumo_real.get(rubro, {})
        teorico = consumo_teorico.get(rubro, {})

        cant_real = real.get('cantidad', 0)
        cant_teorico = teorico.get('cantidad', 0)
        unidad = real.get('unidad') or teorico.get('unidad', '')
        costo = real.get('costo', 0)

        if cant_teorico > 0:
            desvio_pct = round(((cant_real - cant_teorico) / cant_teorico) * 100, 1)
            eficiencia = round((cant_teorico / cant_real) * 100, 1) if cant_real > 0 else 0
        else:
            desvio_pct = 0
            eficiencia = 0

        # Clasificar alerta
        if desvio_pct > 15:
            alerta = 'critico'      # Desperdicio grave o posible robo
            mensaje = 'Consumo excesivo: revisar desperdicio o pérdida'
        elif desvio_pct > 8:
            alerta = 'alerta'       # Por encima de lo normal
            mensaje = 'Consumo por encima del rango esperado'
        elif desvio_pct < -10:
            alerta = 'revisar'      # Muy por debajo: ¿falta registrar?
            mensaje = 'Consumo muy bajo: verificar si falta registrar uso'
        else:
            alerta = 'ok'
            mensaje = 'Dentro del rango esperado'

        costo_por_unidad = round(costo / cant_real, 2) if cant_real > 0 else 0

        comparacion[rubro] = {
            'unidad': unidad,
            'cantidad_real': cant_real,
            'cantidad_teorica': cant_teorico,
            'desvio_cantidad': round(cant_real - cant_teorico, 2),
            'desvio_porcentaje': desvio_pct,
            'eficiencia': eficiencia,
            'costo_total': costo,
            'costo_por_unidad': costo_por_unidad,
            'alerta': alerta,
            'mensaje': mensaje,
        }

    return comparacion


def obtener_nombre_rubro(rubro_key):
    """Devuelve nombre legible del rubro."""
    NOMBRES = {
        'hormigon': 'Hormigón',
        'acero': 'Acero / Hierro',
        'encofrado': 'Encofrado',
        'mamposteria': 'Mampostería',
        'revoque': 'Revoque',
        'contrapiso': 'Contrapiso',
        'pisos': 'Pisos',
        'revestimientos': 'Revestimientos',
        'pintura': 'Pintura',
        'cielorrasos': 'Cielorrasos',
        'impermeabilizacion': 'Impermeabilización',
        'carpinteria': 'Carpintería',
        'inst_electrica': 'Inst. Eléctrica',
        'inst_sanitaria': 'Inst. Sanitaria',
        'inst_gas': 'Inst. Gas',
    }
    return NOMBRES.get(rubro_key, rubro_key.replace('_', ' ').title())
