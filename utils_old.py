"""
Utilidades generales para OBYRA IA
"""

import os
import uuid
from datetime import datetime, date
from werkzeug.utils import secure_filename
from flask import current_app


def generar_nombre_archivo_seguro(filename):
    """Genera un nombre de archivo seguro con timestamp"""
    if filename:
        filename = secure_filename(filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        name, ext = os.path.splitext(filename)
        return f"{timestamp}_{name[:50]}{ext}"
    return None


def crear_directorio_si_no_existe(path):
    """Crea un directorio si no existe"""
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    return path


def formatear_moneda(cantidad):
    """Formatea cantidad como moneda argentina"""
    if cantidad is None:
        return "$0"
    return f"${cantidad:,.0f}".replace(",", ".")


def calcular_progreso_obra(obra):
    """Calcula el progreso de una obra basado en etapas completadas"""
    if not obra.etapas:
        return 0
    
    etapas_completadas = sum(1 for etapa in obra.etapas if etapa.completada)
    total_etapas = obra.etapas.count()
    
    if total_etapas == 0:
        return 0
    
    return int((etapas_completadas / total_etapas) * 100)


def validar_email(email):
    """Validación básica de email"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def calcular_dias_entre_fechas(fecha_inicio, fecha_fin):
    """Calcula días entre dos fechas"""
    if not fecha_inicio or not fecha_fin:
        return 0
    
    if isinstance(fecha_inicio, str):
        fecha_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
    if isinstance(fecha_fin, str):
        fecha_fin = datetime.strptime(fecha_fin, '%Y-%m-%d').date()
    
    return (fecha_fin - fecha_inicio).days


def obtener_estado_obra_color(estado):
    """Obtiene el color CSS para el estado de obra"""
    colores = {
        'planificacion': 'secondary',
        'en_curso': 'primary',
        'pausada': 'warning',
        'finalizada': 'success',
        'cancelada': 'danger'
    }
    return colores.get(estado, 'secondary')


def obtener_prioridad_color(prioridad):
    """Obtiene el color CSS para la prioridad"""
    colores = {
        'baja': 'success',
        'media': 'warning',
        'alta': 'danger',
        'critica': 'danger'
    }
    return colores.get(prioridad, 'secondary')


def generar_numero_presupuesto(obra_id, año=None):
    """Genera un número de presupuesto único"""
    if año is None:
        año = datetime.now().year
    return f"PRES-{obra_id:04d}-{año}"


def generar_codigo_obra(nombre_obra):
    """Genera un código único para la obra"""
    # Tomar las primeras 3 letras del nombre y agregar timestamp
    codigo_base = ''.join([c for c in nombre_obra.upper() if c.isalpha()])[:3]
    if len(codigo_base) < 3:
        codigo_base = codigo_base.ljust(3, 'X')
    
    timestamp = datetime.now().strftime('%m%d')
    return f"{codigo_base}-{timestamp}"


def calcular_iva(monto, tasa=21):
    """Calcula el IVA de un monto"""
    return monto * (tasa / 100)


def redondear_precio(precio):
    """Redondea un precio a los centavos más cercanos"""
    return round(precio, 2)


def obtener_extension_archivo(filename):
    """Obtiene la extensión de un archivo"""
    return os.path.splitext(filename)[1].lower()


def es_archivo_imagen(filename):
    """Verifica si un archivo es una imagen"""
    extensiones_imagen = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg']
    return obtener_extension_archivo(filename) in extensiones_imagen


def es_archivo_documento(filename):
    """Verifica si un archivo es un documento"""
    extensiones_documento = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.rtf']
    return obtener_extension_archivo(filename) in extensiones_documento


def formatear_telefono_argentina(telefono):
    """Formatea un número de teléfono argentino"""
    if not telefono:
        return ""
    
    # Remover caracteres no numéricos
    numeros = ''.join([c for c in telefono if c.isdigit()])
    
    if len(numeros) == 10:
        # Formato: 11-1234-5678
        return f"{numeros[:2]}-{numeros[2:6]}-{numeros[6:]}"
    elif len(numeros) == 8:
        # Formato: 1234-5678
        return f"{numeros[:4]}-{numeros[4:]}"
    
    return telefono


def obtener_texto_estado_presupuesto(estado):
    """Obtiene el texto descriptivo del estado de presupuesto"""
    estados = {
        'borrador': 'En elaboración',
        'enviado': 'Enviado al cliente',
        'aprobado': 'Aprobado por cliente',
        'rechazado': 'Rechazado',
        'vencido': 'Plazo vencido'
    }
    return estados.get(estado, estado.title())


def generar_id_unico():
    """Genera un ID único"""
    return str(uuid.uuid4())


def limpiar_texto(texto):
    """Limpia un texto removiendo espacios extras y caracteres especiales"""
    if not texto:
        return ""
    
    import re
    # Remover espacios extras
    texto = re.sub(r'\s+', ' ', texto.strip())
    return texto


def truncar_texto(texto, longitud=50):
    """Trunca un texto a una longitud específica"""
    if not texto:
        return ""
    
    if len(texto) <= longitud:
        return texto
    
    return texto[:longitud-3] + "..."


def validar_numero_telefono(telefono):
    """Valida un número de teléfono argentino"""
    if not telefono:
        return False
    
    import re
    # Patrón para teléfono argentino (con o sin código de área)
    patron = r'^(\+54\s?)?(\d{2,4})[\s\-]?\d{4}[\s\-]?\d{4}$'
    return re.match(patron, telefono) is not None


def convertir_fecha_string(fecha_str, formato_entrada='%Y-%m-%d', formato_salida='%d/%m/%Y'):
    """Convierte una fecha string de un formato a otro"""
    try:
        fecha = datetime.strptime(fecha_str, formato_entrada)
        return fecha.strftime(formato_salida)
    except:
        return fecha_str


def calcular_diferencia_porcentual(valor_actual, valor_anterior):
    """Calcula la diferencia porcentual entre dos valores"""
    if valor_anterior == 0:
        return 100 if valor_actual > 0 else 0
    
    return ((valor_actual - valor_anterior) / valor_anterior) * 100


def obtener_mes_nombre(numero_mes):
    """Obtiene el nombre del mes en español"""
    meses = {
        1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
        5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
        9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
    }
    return meses.get(numero_mes, '')


def agrupar_por_fecha(items, campo_fecha='fecha_creacion'):
    """Agrupa items por fecha"""
    grupos = {}
    
    for item in items:
        fecha = getattr(item, campo_fecha)
        if isinstance(fecha, datetime):
            fecha = fecha.date()
        
        fecha_str = fecha.strftime('%Y-%m-%d') if fecha else 'Sin fecha'
        
        if fecha_str not in grupos:
            grupos[fecha_str] = []
        
        grupos[fecha_str].append(item)
    
    return grupos


def calcular_promedio(valores):
    """Calcula el promedio de una lista de valores"""
    if not valores:
        return 0
    
    valores_numericos = [v for v in valores if isinstance(v, (int, float))]
    
    if not valores_numericos:
        return 0
    
    return sum(valores_numericos) / len(valores_numericos)


def crear_backup_archivo(ruta_archivo):
    """Crea un backup de un archivo"""
    if os.path.exists(ruta_archivo):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        nombre_backup = f"{ruta_archivo}.backup_{timestamp}"

        import shutil
        shutil.copy2(ruta_archivo, nombre_backup)
        return nombre_backup

    return None


# ===== FUNCIONES DE CONVERSIÓN SEGURA (SEGURIDAD) =====

def safe_decimal(value, default=0):
    """Convierte a Decimal de forma segura

    Args:
        value: Valor a convertir
        default: Valor por defecto si falla la conversión

    Returns:
        Decimal: Valor convertido o default
    """
    from decimal import Decimal, InvalidOperation
    try:
        if value is None or value == '':
            return Decimal(default)
        result = Decimal(str(value))
        if result < 0:
            return Decimal(default)
        return result
    except (ValueError, InvalidOperation, TypeError):
        return Decimal(default)


def safe_float(value, default=0.0):
    """Convierte a float de forma segura

    Args:
        value: Valor a convertir
        default: Valor por defecto si falla la conversión

    Returns:
        float: Valor convertido o default
    """
    try:
        if value is None or value == '':
            return default
        result = float(value)
        if result < 0:
            return default
        return result
    except (ValueError, TypeError):
        return default


def safe_int(value, default=0):
    """Convierte a int de forma segura

    Args:
        value: Valor a convertir
        default: Valor por defecto si falla la conversión

    Returns:
        int: Valor convertido o default
    """
    try:
        if value is None or value == '':
            return default
        result = int(value)
        if result < 0:
            return default
        return result
    except (ValueError, TypeError):
        return default