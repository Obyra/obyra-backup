"""
Matcher de etapas: convierte nombres libres (de Excel de licitacion, etc.)
a etapas estandar del sistema OBYRA.

Util para que diferentes formatos de presupuestos se normalicen al mismo
catalogo y se pueda comparar/agrupar/convertir a obra de manera consistente.
"""
import re
import unicodedata


# Etapas estandar del sistema (sincronizado con tareas_predefinidas.py
# y el flujo de creacion de obra).
ETAPAS_ESTANDAR = {
    'Preliminares y Organizacion': [
        'organizacion', 'preliminar', 'gestion', 'permiso', 'habilitacion',
        'cartel', 'tramites', 'documentacion', 'planos', 'replanteo',
        'limpieza inicial', 'cumplimiento', 'supervision', 'jefatura', 'control de acceso',
    ],
    'Items Complementarios': [
        'complementario', 'complemetario', 'sereno', 'vigilancia', 'grupo electrogeno',
        'energia electrica obrador', 'obrador', 'bano quimico', 'items varios',
    ],
    'Movimiento de Suelos': [
        'movimiento de suelo', 'excavacion', 'relleno', 'desbroce', 'terreno',
        'nivelacion', 'cateo', 'protec', 'talud',
    ],
    'Demoliciones': [
        'demolicion', 'rotura', 'picado', 'corte de canaleta', 'media sombra de proteccion',
    ],
    'Depresion de Napa': [
        'depresion de napa', 'napa', 'bombeo', 'cegado de anclaje', 'red depresora',
    ],
    'Apuntalamientos': [
        'apuntalamiento', 'apuntalar',
    ],
    'Fundaciones': [
        'fundacion', 'cimiento', 'zapata', 'platea', 'pilote', 'submuracion',
        'viga de fundacion',
    ],
    'Estructura de Hormigon Armado': [
        'estructura de h', 'hormigon armado', 'losa', 'columna', 'viga',
        'tabique', 'estructura', 'h°a°', 'hºaº',
    ],
    'Mamposteria': [
        'mamposteria', 'mamposter', 'muro', 'pared', 'tabique de ladrillo',
        'bloque', 'ladrillo',
    ],
    'Cubiertas y Techos': [
        'cubierta', 'techo', 'teja', 'chapa', 'impermeabilizacion',
    ],
    'Aislaciones': [
        'aislacion', 'aislante', 'membrana', 'barrera vapor', 'lana de vidrio',
    ],
    'Revoques': [
        'revoque', 'azotado', 'jaharro', 'enlucido de cemento',
    ],
    'Yeseria y Construccion en Seco': [
        'yeseria', 'yeso', 'enlucido de yeso', 'durlock', 'placa de yeso',
        'construccion en seco', 'tabique seco', 'cielorraso de placa',
    ],
    'Contrapisos y Carpetas': [
        'contrapiso', 'carpeta', 'capa niveladora',
    ],
    'Pisos': [
        'piso', 'ceramica', 'porcelanato', 'granito', 'parquet', 'flotante',
        'baldosa', 'mosaico',
    ],
    'Zocalos y Guardacantos': [
        'zocalo', 'guardacanto', 'cantonera',
    ],
    'Carpinterias': [
        'carpinteria', 'puerta', 'ventana', 'marco', 'mampara', 'placard',
        'aluminio', 'pvc', 'madera estructural',
    ],
    'Vidrios y Cristales': [
        'vidrio', 'cristal', 'espejo', 'doble vidriado', 'dvh',
    ],
    'Herreria y Aberturas Metalicas': [
        'herreria', 'baranda', 'reja', 'porton metalico', 'escalera metalica',
        'metalica', 'metalico',
    ],
    'Instalacion Electrica': [
        'instalacion electrica', 'electric', 'cable', 'tablero', 'luminaria',
        'tomacorriente', 'iluminacion', 'corriente debil',
    ],
    'Instalacion Sanitaria': [
        'instalacion sanitaria', 'sanitari', 'desague', 'cañeria', 'inodoro',
        'lavabo', 'agua fria', 'agua caliente', 'cloacal', 'pluvial',
    ],
    'Instalacion de Gas': [
        'gas', 'gasoducto', 'artefacto a gas', 'gabinete de gas',
    ],
    'Climatizacion': [
        'aire acondicionado', 'calefaccion', 'ventilacion', 'split', 'vrv',
        'extraccion forzada', 'climat',
    ],
    'Ascensores': [
        'ascensor', 'montacarga', 'plataforma elevadora',
    ],
    'Pintura': [
        'pintura', 'latex', 'esmalte', 'barniz', 'enduido',
    ],
    'Equipamiento': [
        'equipamiento', 'amoblamiento', 'amoblado', 'mueble',
    ],
    'Limpieza Final': [
        'limpieza final', 'acondicionamiento final', 'destapacion',
    ],
}


def _normalizar(texto):
    """Quita acentos y pasa a minusculas."""
    if not texto:
        return ''
    s = unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode()
    return s.lower().strip()


def matchear_etapa_estandar(texto):
    """Recibe un string libre (etapa del Excel o descripcion) y retorna
    el nombre de etapa estandar mas probable, o None si no hay match.

    Args:
        texto: nombre de etapa del Excel (ej: 'ESTRUCTURAS DE Hº Aº FUDACIONES')

    Retorna: 'Estructura de Hormigon Armado' o None
    """
    if not texto:
        return None

    t = _normalizar(texto)
    if not t:
        return None

    # Buscar la etapa con mas keywords coincidentes
    mejor = None
    mejor_score = 0

    for etapa, keywords in ETAPAS_ESTANDAR.items():
        score = 0
        for kw in keywords:
            kw_norm = _normalizar(kw)
            if kw_norm and kw_norm in t:
                # Dar mas peso a keywords largas (mas especificas)
                score += len(kw_norm.split()) + 1
        if score > mejor_score:
            mejor_score = score
            mejor = etapa

    return mejor if mejor_score >= 1 else None


def matchear_etapa_para_item(descripcion_item, etapa_excel=None):
    """Intenta matchear primero por etapa del Excel y, si no hay match,
    por descripcion del item.

    Util porque a veces la etapa del Excel es generica (ej: 'OTROS') y
    la descripcion del item da mas pistas.
    """
    # Prioridad 1: etapa del Excel
    if etapa_excel:
        m = matchear_etapa_estandar(etapa_excel)
        if m:
            return m
    # Prioridad 2: descripcion del item
    if descripcion_item:
        return matchear_etapa_estandar(descripcion_item)
    return None
