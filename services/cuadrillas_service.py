"""
Servicio de Cuadrillas y Escala Salarial UOCRA.
Gestión de cuadrillas tipo, escala salarial, y seed de datos iniciales.
"""
from datetime import date
from decimal import Decimal
from extensions import db
from models.budgets import EscalaSalarialUOCRA, CuadrillaTipo, MiembroCuadrilla


# ============================================================
# ESCALA SALARIAL UOCRA - Marzo 2026 (referencia)
# Fuente: Convenio Colectivo UOCRA
# ============================================================
ESCALA_UOCRA_DEFAULT = [
    {'categoria': 'oficial_especializado', 'descripcion': 'Oficial especializado (encofrador, gruísta, etc.)', 'jornal': 56000},
    {'categoria': 'oficial',              'descripcion': 'Oficial albañil / plomero / electricista',          'jornal': 48000},
    {'categoria': 'medio_oficial',        'descripcion': 'Medio oficial',                                      'jornal': 42000},
    {'categoria': 'ayudante',             'descripcion': 'Ayudante / peón',                                    'jornal': 36000},
    {'categoria': 'sereno',               'descripcion': 'Sereno / vigilancia',                                'jornal': 34000},
    {'categoria': 'maquinista',           'descripcion': 'Operador de maquinaria pesada',                      'jornal': 58000},
]


# ============================================================
# CUADRILLAS TIPO POR ETAPA Y TIPO DE OBRA
# ============================================================
# Estructura: etapa_tipo → tipo_obra → {nombre, rendimiento, unidad, miembros}
# rendimiento = cuánto produce esta cuadrilla por día
# miembros = [{rol, categoria, cantidad}]

CUADRILLAS_DEFAULT = {
    'excavacion': {
        'economica': {
            'nombre': 'Excavación manual',
            'rendimiento': 8.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 3},
            ]
        },
        'estandar': {
            'nombre': 'Excavación con mini retro',
            'rendimiento': 25.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Maquinista', 'categoria': 'maquinista', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 2},
            ]
        },
        'premium': {
            'nombre': 'Excavación con retro + camión',
            'rendimiento': 50.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Maquinista retro', 'categoria': 'maquinista', 'cantidad': 1},
                {'rol': 'Maquinista camión', 'categoria': 'maquinista', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
    },
    'fundaciones': {
        'economica': {
            'nombre': 'Fundaciones - encofrado madera',
            'rendimiento': 4.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 2},
                {'rol': 'Encofrador', 'categoria': 'oficial_especializado', 'cantidad': 1},
            ]
        },
        'estandar': {
            'nombre': 'Fundaciones - encofrado metálico',
            'rendimiento': 6.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 2},
                {'rol': 'Encofrador', 'categoria': 'oficial_especializado', 'cantidad': 1},
            ]
        },
        'premium': {
            'nombre': 'Fundaciones - sistema industrializado',
            'rendimiento': 10.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 2},
                {'rol': 'Encofrador PERI', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Gruísta', 'categoria': 'maquinista', 'cantidad': 0.5},
            ]
        },
    },
    'estructura': {
        'economica': {
            'nombre': 'Estructura - encofrado madera',
            'rendimiento': 3.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 2},
                {'rol': 'Encofrador madera', 'categoria': 'oficial_especializado', 'cantidad': 2},
                {'rol': 'Fierrero', 'categoria': 'oficial_especializado', 'cantidad': 1},
            ]
        },
        'estandar': {
            'nombre': 'Estructura - sistema PERI',
            'rendimiento': 5.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 2},
                {'rol': 'Encofrador PERI', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Fierrero', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Gruísta', 'categoria': 'maquinista', 'cantidad': 0.5},
            ]
        },
        'premium': {
            'nombre': 'Estructura - PERI trepante + grúa torre',
            'rendimiento': 8.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
                {'rol': 'Operador PERI trepante', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Fierrero', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Gruísta torre', 'categoria': 'maquinista', 'cantidad': 1},
            ]
        },
    },
    'mamposteria': {
        'economica': {
            'nombre': 'Mampostería ladrillo común',
            'rendimiento': 10.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Oficial albañil', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'estandar': {
            'nombre': 'Mampostería bloque cerámico',
            'rendimiento': 14.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Oficial albañil', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'premium': {
            'nombre': 'Mampostería bloque HCCA / Retak',
            'rendimiento': 18.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Oficial albañil', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Medio oficial', 'categoria': 'medio_oficial', 'cantidad': 1},
            ]
        },
    },
    'instalacion_electrica': {
        'economica': {
            'nombre': 'Instalación eléctrica básica',
            'rendimiento': 25.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Electricista', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'estandar': {
            'nombre': 'Instalación eléctrica estándar',
            'rendimiento': 20.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Electricista', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'premium': {
            'nombre': 'Instalación eléctrica + domótica',
            'rendimiento': 15.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Electricista', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Técnico domótica', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
    },
    'instalacion_sanitaria': {
        'economica': {
            'nombre': 'Sanitaria básica',
            'rendimiento': 30.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Plomero', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'estandar': {
            'nombre': 'Sanitaria estándar',
            'rendimiento': 25.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Plomero', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'premium': {
            'nombre': 'Sanitaria premium + calefacción',
            'rendimiento': 18.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Plomero', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Gasista', 'categoria': 'oficial_especializado', 'cantidad': 0.5},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
    },
    'revoques': {
        'economica': {
            'nombre': 'Revoque grueso + fino manual',
            'rendimiento': 8.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Oficial albañil', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'estandar': {
            'nombre': 'Revoque proyectado',
            'rendimiento': 20.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'premium': {
            'nombre': 'Revoque proyectado + terminación',
            'rendimiento': 25.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Medio oficial', 'categoria': 'medio_oficial', 'cantidad': 1},
            ]
        },
    },
    'pintura': {
        'economica': {
            'nombre': 'Pintura látex interior',
            'rendimiento': 30.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Pintor', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'estandar': {
            'nombre': 'Pintura interior + exterior',
            'rendimiento': 25.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Pintor', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'premium': {
            'nombre': 'Pintura premium + texturados',
            'rendimiento': 18.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Pintor especializado', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Pintor', 'categoria': 'oficial', 'cantidad': 1},
            ]
        },
    },
    'pisos': {
        'economica': {
            'nombre': 'Contrapiso + alisado cemento',
            'rendimiento': 12.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'estandar': {
            'nombre': 'Contrapiso + cerámico',
            'rendimiento': 10.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Oficial colocador', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
        'premium': {
            'nombre': 'Contrapiso + porcelanato gran formato',
            'rendimiento': 8.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Colocador especializado', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
            ]
        },
    },
    'techos': {
        'economica': {
            'nombre': 'Techo chapa + estructura madera',
            'rendimiento': 12.0, 'unidad': 'm2',
            'miembros': [
                {'rol': 'Carpintero', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 2},
            ]
        },
        'estandar': {
            'nombre': 'Techo losa + membrana',
            'rendimiento': 4.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 2},
                {'rol': 'Encofrador', 'categoria': 'oficial_especializado', 'cantidad': 1},
            ]
        },
        'premium': {
            'nombre': 'Techo losa + aislación + terminación',
            'rendimiento': 6.0, 'unidad': 'm3',
            'miembros': [
                {'rol': 'Oficial', 'categoria': 'oficial', 'cantidad': 1},
                {'rol': 'Ayudante', 'categoria': 'ayudante', 'cantidad': 1},
                {'rol': 'Encofrador PERI', 'categoria': 'oficial_especializado', 'cantidad': 1},
                {'rol': 'Gruísta', 'categoria': 'maquinista', 'cantidad': 0.5},
            ]
        },
    },
}


def seed_escala_salarial(organizacion_id, vigencia_desde=None):
    """Crea la escala salarial UOCRA por defecto para una organización.
    Si ya existe, no duplica."""
    if vigencia_desde is None:
        vigencia_desde = date(2026, 3, 1)

    existentes = EscalaSalarialUOCRA.query.filter_by(
        organizacion_id=organizacion_id, activo=True
    ).count()
    if existentes > 0:
        return  # Ya tiene escala cargada

    for item in ESCALA_UOCRA_DEFAULT:
        escala = EscalaSalarialUOCRA(
            organizacion_id=organizacion_id,
            categoria=item['categoria'],
            descripcion=item['descripcion'],
            jornal=Decimal(str(item['jornal'])),
            tarifa_hora=Decimal(str(item['jornal'])) / Decimal('8'),
            vigencia_desde=vigencia_desde,
            activo=True,
        )
        db.session.add(escala)

    db.session.flush()


def seed_cuadrillas_default(organizacion_id):
    """Crea las cuadrillas tipo por defecto para una organización.
    Si ya existe, no duplica."""
    existentes = CuadrillaTipo.query.filter_by(
        organizacion_id=organizacion_id, activo=True
    ).count()
    if existentes > 0:
        return

    # Primero asegurar que existe la escala salarial
    seed_escala_salarial(organizacion_id)

    # Obtener escalas por categoría
    escalas = {}
    for e in EscalaSalarialUOCRA.query.filter_by(
        organizacion_id=organizacion_id, activo=True
    ).all():
        escalas[e.categoria] = e

    for etapa_tipo, tipos_obra in CUADRILLAS_DEFAULT.items():
        for tipo_obra, config in tipos_obra.items():
            cuadrilla = CuadrillaTipo(
                organizacion_id=organizacion_id,
                nombre=config['nombre'],
                etapa_tipo=etapa_tipo,
                tipo_obra=tipo_obra,
                rendimiento_diario=Decimal(str(config['rendimiento'])),
                unidad_rendimiento=config['unidad'],
                activo=True,
            )
            db.session.add(cuadrilla)
            db.session.flush()

            for m in config['miembros']:
                escala = escalas.get(m['categoria'])
                miembro = MiembroCuadrilla(
                    cuadrilla_id=cuadrilla.id,
                    escala_id=escala.id if escala else None,
                    rol=m['rol'],
                    cantidad=Decimal(str(m['cantidad'])),
                )
                db.session.add(miembro)

    db.session.commit()


def obtener_cuadrilla(organizacion_id, etapa_tipo, tipo_obra='estandar'):
    """Busca la cuadrilla tipo para una etapa y tipo de obra.
    Fallback: si no hay para el tipo exacto, busca estándar."""
    cuadrilla = CuadrillaTipo.query.filter_by(
        organizacion_id=organizacion_id,
        etapa_tipo=etapa_tipo,
        tipo_obra=tipo_obra,
        activo=True,
    ).first()

    if not cuadrilla and tipo_obra != 'estandar':
        cuadrilla = CuadrillaTipo.query.filter_by(
            organizacion_id=organizacion_id,
            etapa_tipo=etapa_tipo,
            tipo_obra='estandar',
            activo=True,
        ).first()

    return cuadrilla


def calcular_mo_etapa(organizacion_id, etapa_tipo, cantidad_trabajo, tipo_obra='estandar'):
    """Calcula el costo de MO para una etapa usando cuadrillas tipo.

    Args:
        organizacion_id: ID de la organización
        etapa_tipo: 'excavacion', 'estructura', etc.
        cantidad_trabajo: m2, m3, etc. según la etapa
        tipo_obra: 'economica', 'estandar', 'premium'

    Returns:
        dict con jornales, dias, costo_total, composicion, etc.
    """
    cuadrilla = obtener_cuadrilla(organizacion_id, etapa_tipo, tipo_obra)
    if not cuadrilla:
        return None

    result = cuadrilla.calcular_jornales(cantidad_trabajo)
    result['cuadrilla_nombre'] = cuadrilla.nombre
    result['cuadrilla_id'] = cuadrilla.id
    result['unidad'] = cuadrilla.unidad_rendimiento
    result['rendimiento_diario'] = float(cuadrilla.rendimiento_diario)
    result['composicion'] = [
        {
            'rol': m.rol,
            'cantidad': float(m.cantidad),
            'jornal': float(m.jornal_override or (m.escala.jornal if m.escala else 0)),
            'categoria': m.escala.categoria if m.escala else None,
        }
        for m in cuadrilla.miembros
    ]

    return result


def obtener_escala_vigente(organizacion_id):
    """Retorna la escala salarial vigente de la organización."""
    return EscalaSalarialUOCRA.query.filter_by(
        organizacion_id=organizacion_id,
        activo=True,
    ).order_by(EscalaSalarialUOCRA.vigencia_desde.desc()).all()


def actualizar_escala(organizacion_id, nuevos_valores, vigencia_desde=None):
    """Actualiza la escala salarial.

    Args:
        organizacion_id: ID org
        nuevos_valores: [{categoria, jornal}]
        vigencia_desde: fecha desde cuándo rige (default: hoy)
    """
    if vigencia_desde is None:
        vigencia_desde = date.today()

    # Desactivar escala anterior
    EscalaSalarialUOCRA.query.filter_by(
        organizacion_id=organizacion_id, activo=True
    ).update({'activo': False, 'vigencia_hasta': vigencia_desde})

    # Crear nueva escala
    for item in nuevos_valores:
        jornal = Decimal(str(item['jornal']))
        escala = EscalaSalarialUOCRA(
            organizacion_id=organizacion_id,
            categoria=item['categoria'],
            descripcion=item.get('descripcion', ''),
            jornal=jornal,
            tarifa_hora=jornal / Decimal('8'),
            vigencia_desde=vigencia_desde,
            activo=True,
        )
        db.session.add(escala)

    db.session.commit()
