"""
Servicio para cargar datos de ejemplo en una organizacion nueva.

Crea una obra de demostracion completa con:
- Cliente de ejemplo
- Obra "Casa de muestra - Demo"
- 4 etapas (Cimientos, Estructura, Mamposteria, Instalaciones)
- Tareas dentro de cada etapa
- Presupuesto basico

Idempotente: si ya existe una obra con nombre "[DEMO] ..." no crea otra.
"""
from datetime import date, timedelta
from decimal import Decimal

from extensions import db
from models import Obra, EtapaObra, TareaEtapa, Cliente


def organizacion_tiene_demo(org_id):
    return Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.nombre.like('[DEMO]%')
    ).first() is not None


def crear_obra_demo(org_id, user_id=None):
    """Crea una obra demo completa. Idempotente.

    Returns: (obra, created) tuple. created=False si ya existia.
    """
    existente = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.nombre.like('[DEMO]%')
    ).first()
    if existente:
        return existente, False

    hoy = date.today()

    # 1. Cliente demo
    cliente = Cliente.query.filter_by(
        organizacion_id=org_id,
        empresa='Constructora Ejemplo SA'
    ).first()
    if not cliente:
        cliente = Cliente(
            organizacion_id=org_id,
            nombre='Juan',
            apellido='Perez',
            empresa='Constructora Ejemplo SA',
            tipo_documento='CUIT',
            numero_documento='30-12345678-9',
            email='ejemplo@constructora.com',
            telefono='+54 11 1234-5678',
            ciudad='Buenos Aires',
            provincia='CABA',
            activo=True,
        )
        db.session.add(cliente)
        db.session.flush()

    # 2. Obra demo
    obra = Obra(
        organizacion_id=org_id,
        nombre='[DEMO] Casa de muestra',
        descripcion='Obra de ejemplo precargada para mostrar las funcionalidades de OBYRA. Podes editarla o eliminarla cuando quieras.',
        direccion='Av. Corrientes 1234, Buenos Aires',
        ciudad='Buenos Aires',
        provincia='CABA',
        pais='Argentina',
        cliente='Constructora Ejemplo SA',
        cliente_id=cliente.id,
        cliente_nombre='Juan Perez',
        cliente_email='ejemplo@constructora.com',
        cliente_telefono='+54 11 1234-5678',
        telefono_cliente='+54 11 1234-5678',
        email_cliente='ejemplo@constructora.com',
        fecha_inicio=hoy,
        fecha_fin_estimada=hoy + timedelta(days=180),
        estado='en_curso',
        presupuesto_total=Decimal('15000000.00'),
        progreso=25,
    )
    db.session.add(obra)
    db.session.flush()

    # 3. Etapas + tareas
    etapas_demo = [
        {
            'nombre': 'Cimientos',
            'progreso': 100,
            'estado': 'finalizada',
            'tareas': [
                ('Excavacion', 'completada'),
                ('Hormigon de limpieza', 'completada'),
                ('Armado de hierros', 'completada'),
                ('Hormigonado de bases', 'completada'),
            ],
        },
        {
            'nombre': 'Estructura',
            'progreso': 60,
            'estado': 'en_curso',
            'tareas': [
                ('Columnas planta baja', 'completada'),
                ('Vigas planta baja', 'completada'),
                ('Losa planta alta', 'en_curso'),
                ('Columnas planta alta', 'pendiente'),
            ],
        },
        {
            'nombre': 'Mamposteria',
            'progreso': 0,
            'estado': 'pendiente',
            'tareas': [
                ('Muros exteriores', 'pendiente'),
                ('Tabiques interiores', 'pendiente'),
                ('Revoque grueso', 'pendiente'),
            ],
        },
        {
            'nombre': 'Instalaciones',
            'progreso': 0,
            'estado': 'pendiente',
            'tareas': [
                ('Instalacion electrica', 'pendiente'),
                ('Instalacion sanitaria', 'pendiente'),
                ('Instalacion de gas', 'pendiente'),
            ],
        },
    ]

    fecha_acumulada = hoy
    for orden, et_data in enumerate(etapas_demo, start=1):
        duracion_dias = 30
        etapa = EtapaObra(
            obra_id=obra.id,
            nombre=et_data['nombre'],
            descripcion=f'Etapa demo: {et_data["nombre"]}',
            orden=orden,
            estado=et_data['estado'],
            progreso=et_data['progreso'],
            fecha_inicio_estimada=fecha_acumulada,
            fecha_fin_estimada=fecha_acumulada + timedelta(days=duracion_dias),
            unidad_medida='m2',
            cantidad_total_planificada=Decimal('100'),
            cantidad_total_ejecutada=Decimal(str(et_data['progreso'])),
        )
        db.session.add(etapa)
        db.session.flush()

        for nombre_tarea, estado_tarea in et_data['tareas']:
            tarea = TareaEtapa(
                etapa_id=etapa.id,
                nombre=nombre_tarea,
                descripcion=f'Tarea demo: {nombre_tarea}',
                fecha_inicio_estimada=fecha_acumulada,
                fecha_fin_estimada=fecha_acumulada + timedelta(days=duracion_dias // len(et_data['tareas'])),
                estado=estado_tarea,
                horas_estimadas=Decimal('40'),
                porcentaje_avance=Decimal('100') if estado_tarea == 'completada' else (Decimal('50') if estado_tarea == 'en_curso' else Decimal('0')),
            )
            db.session.add(tarea)

        fecha_acumulada += timedelta(days=duracion_dias)

    db.session.commit()
    return obra, True


def eliminar_obra_demo(org_id):
    """Elimina la obra demo de una organizacion (si existe)."""
    obra = Obra.query.filter(
        Obra.organizacion_id == org_id,
        Obra.nombre.like('[DEMO]%')
    ).first()
    if not obra:
        return False
    obra.soft_delete()
    db.session.commit()
    return True
