from datetime import datetime, date
from decimal import Decimal
import re

def formatear_fecha(fecha):
    """Formatea una fecha para mostrar en español"""
    if not fecha:
        return ""
    
    if isinstance(fecha, str):
        try:
            fecha = datetime.strptime(fecha, '%Y-%m-%d').date()
        except ValueError:
            return fecha
    
    meses = {
        1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
        5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
        9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'
    }
    
    return f"{fecha.day} de {meses[fecha.month]} de {fecha.year}"

def formatear_moneda(valor):
    """Formatea un valor como moneda argentina"""
    if valor is None:
        return "$0,00"
    
    if isinstance(valor, (int, float, Decimal)):
        valor = float(valor)
    else:
        try:
            valor = float(valor)
        except (ValueError, TypeError):
            return "$0,00"
    
    return f"${valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def formatear_numero(valor, decimales=2):
    """Formatea un número con separadores de miles y decimales"""
    if valor is None:
        return "0"
    
    if isinstance(valor, (int, float, Decimal)):
        valor = float(valor)
    else:
        try:
            valor = float(valor)
        except (ValueError, TypeError):
            return "0"
    
    if decimales == 0:
        return f"{int(valor):,}".replace(',', '.')
    else:
        formato = f"{{:,.{decimales}f}}"
        return formato.format(valor).replace(',', 'X').replace('.', ',').replace('X', '.')

def validar_email(email):
    """Valida formato de email"""
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(patron, email) is not None

def validar_telefono(telefono):
    """Valida formato de teléfono argentino"""
    if not telefono:
        return True  # Teléfono es opcional
    
    # Eliminar espacios y guiones
    telefono = re.sub(r'[\s\-\(\)]', '', telefono)
    
    # Patrones válidos para Argentina
    patrones = [
        r'^\+5411\d{8}$',  # +54 11 XXXX XXXX (CABA)
        r'^\+54\d{10}$',   # +54 XXX XXX XXXX (Interior)
        r'^11\d{8}$',      # 11 XXXX XXXX (CABA sin código país)
        r'^\d{10}$',       # XXX XXX XXXX (Interior sin código país)
        r'^15\d{8}$',      # 15 XXXX XXXX (Celular)
    ]
    
    return any(re.match(patron, telefono) for patron in patrones)

def calcular_progreso_obra(obra):
    """Calcula el progreso de una obra basado en sus etapas"""
    if not obra.etapas:
        return 0
    
    total_etapas = obra.etapas.count()
    etapas_completadas = obra.etapas.filter_by(estado='finalizada').count()
    
    if total_etapas == 0:
        return 0
    
    return int((etapas_completadas / total_etapas) * 100)

def generar_codigo_item(categoria, nombre):
    """Genera un código automático para un item de inventario"""
    # Tomar las primeras 3 letras de la categoría
    prefijo = categoria[:3].upper()
    
    # Tomar las primeras 3 letras del nombre (sin espacios)
    nombre_clean = re.sub(r'[^a-zA-Z]', '', nombre)
    sufijo = nombre_clean[:3].upper()
    
    # Generar número secuencial
    from models import ItemInventario
    ultimo_numero = ItemInventario.query.filter(
        ItemInventario.codigo.like(f'{prefijo}{sufijo}%')
    ).count()
    
    numero = f"{ultimo_numero + 1:03d}"
    
    return f"{prefijo}{sufijo}{numero}"

def estados_obra():
    """Retorna los estados posibles de una obra"""
    return [
        ('planificacion', 'Planificación'),
        ('en_curso', 'En Curso'),
        ('pausada', 'Pausada'),
        ('finalizada', 'Finalizada'),
        ('cancelada', 'Cancelada')
    ]

def roles_usuario():
    """Retorna los roles posibles de usuario"""
    return [
        ('administrador', 'Administrador'),
        ('tecnico', 'Técnico'),
        ('operario', 'Operario')
    ]

def tipos_inventario():
    """Retorna los tipos de inventario"""
    return [
        ('material', 'Material'),
        ('herramienta', 'Herramienta'),
        ('maquinaria', 'Maquinaria')
    ]

def unidades_medida():
    """Retorna las unidades de medida comunes"""
    return [
        ('unidad', 'Unidad'),
        ('metro', 'Metro'),
        ('metro2', 'Metro²'),
        ('metro3', 'Metro³'),
        ('kilogramo', 'Kilogramo'),
        ('tonelada', 'Tonelada'),
        ('litro', 'Litro'),
        ('hora', 'Hora'),
        ('dia', 'Día'),
        ('bolsa', 'Bolsa'),
        ('caja', 'Caja'),
        ('paquete', 'Paquete')
    ]

def calcular_dias_habiles(fecha_inicio, fecha_fin):
    """Calcula los días hábiles entre dos fechas (excluyendo fines de semana)"""
    if not fecha_inicio or not fecha_fin:
        return 0
    
    dias = 0
    fecha_actual = fecha_inicio
    
    while fecha_actual <= fecha_fin:
        # 0 = lunes, 6 = domingo
        if fecha_actual.weekday() < 5:  # lunes a viernes
            dias += 1
        fecha_actual += timedelta(days=1)
    
    return dias

def validar_cuit(cuit):
    """Valida un CUIT argentino"""
    if not cuit:
        return False
    
    # Eliminar guiones
    cuit = re.sub(r'[\-\s]', '', cuit)
    
    # Verificar longitud
    if len(cuit) != 11:
        return False
    
    # Verificar que sean todos números
    if not cuit.isdigit():
        return False
    
    # Algoritmo de verificación
    multiplicadores = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = sum(int(cuit[i]) * multiplicadores[i] for i in range(10))
    
    resto = suma % 11
    digito_verificador = 11 - resto if resto >= 2 else resto
    
    return int(cuit[10]) == digito_verificador

# Filtros personalizados para Jinja2
def registrar_filtros(app):
    """Registra filtros personalizados para las plantillas"""
    
    @app.template_filter('fecha')
    def filtro_fecha(fecha):
        return formatear_fecha(fecha)
    
    @app.template_filter('moneda')
    def filtro_moneda(valor):
        return formatear_moneda(valor)
    
    @app.template_filter('numero')
    def filtro_numero(valor, decimales=2):
        return formatear_numero(valor, decimales)
    
    @app.template_filter('estado_badge')
    def filtro_estado_badge(estado):
        """Retorna la clase CSS para badges de estado"""
        clases = {
            'planificacion': 'bg-info',
            'en_curso': 'bg-primary',
            'pausada': 'bg-warning',
            'finalizada': 'bg-success',
            'cancelada': 'bg-danger',
            'borrador': 'bg-secondary',
            'enviado': 'bg-info',
            'aprobado': 'bg-success',
            'rechazado': 'bg-danger',
            'pendiente': 'bg-warning',
            'activo': 'bg-success',
            'inactivo': 'bg-secondary'
        }
        return clases.get(estado, 'bg-secondary')
