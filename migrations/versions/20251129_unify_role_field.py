"""Unificar campo rol -> role en usuarios

Esta migración:
1. Copia datos de 'rol' a 'role' mapeando valores equivalentes
2. Marca el campo 'rol' como deprecated (no lo elimina aún para seguridad)

Mapeo de roles:
- 'administrador' -> 'admin'
- 'tecnico' -> 'tecnico'
- 'operario' -> 'operario'
- 'jefe_obra' -> 'pm'
- 'project_manager' -> 'pm'
- otros roles específicos de construcción -> 'tecnico' o 'operario'

Revision ID: 20251129_unify_role
Revises: 202511070001_add_clientes_table
Create Date: 2025-11-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '20251129_unify_role'
down_revision = '202511070001'
branch_labels = None
depends_on = None


# Mapeo de roles antiguos a nuevos
ROLE_MAPPING = {
    # Roles administrativos -> admin
    'administrador': 'admin',
    'administrador_general': 'admin',
    'admin_empresa': 'admin',
    'superadmin': 'admin',
    'director_general': 'admin',
    'director_operaciones': 'admin',

    # Roles de gestión -> pm
    'jefe_obra': 'pm',
    'project_manager': 'pm',
    'director_proyectos': 'pm',
    'coordinador_proyectos': 'pm',
    'jefe_produccion': 'pm',
    'administrador_obra': 'pm',

    # Roles técnicos -> tecnico
    'tecnico': 'tecnico',
    'ingeniero_civil': 'tecnico',
    'ingeniero_construcciones': 'tecnico',
    'arquitecto': 'tecnico',
    'ingeniero_seguridad': 'tecnico',
    'ingeniero_electrico': 'tecnico',
    'ingeniero_sanitario': 'tecnico',
    'ingeniero_mecanico': 'tecnico',
    'topografo': 'tecnico',
    'bim_manager': 'tecnico',
    'computo_presupuesto': 'tecnico',
    'encargado_obra': 'tecnico',
    'supervisor_obra': 'tecnico',
    'inspector_calidad': 'tecnico',
    'inspector_seguridad': 'tecnico',
    'supervisor_especialidades': 'tecnico',
    'comprador': 'tecnico',
    'logistica': 'tecnico',
    'recursos_humanos': 'tecnico',
    'contador_finanzas': 'tecnico',

    # Roles operativos -> operario
    'operario': 'operario',
    'capataz': 'operario',
    'maestro_mayor_obra': 'operario',
    'oficial_albanil': 'operario',
    'oficial_plomero': 'operario',
    'oficial_electricista': 'operario',
    'oficial_herrero': 'operario',
    'oficial_pintor': 'operario',
    'oficial_yesero': 'operario',
    'medio_oficial': 'operario',
    'ayudante': 'operario',
    'operador_maquinaria': 'operario',
    'chofer_camion': 'operario',
}


def upgrade():
    """Migrar datos de rol a role con mapeo correcto."""
    connection = op.get_bind()

    # Construir el CASE statement para el UPDATE
    case_parts = []
    for old_role, new_role in ROLE_MAPPING.items():
        case_parts.append(f"WHEN LOWER(rol) = '{old_role}' THEN '{new_role}'")

    case_statement = " ".join(case_parts)

    # Actualizar role basándose en rol donde role está vacío o es 'operario' por defecto
    # y rol tiene un valor significativo
    sql = f"""
    UPDATE usuarios
    SET role = CASE
        {case_statement}
        ELSE COALESCE(NULLIF(LOWER(role), ''), 'operario')
    END
    WHERE rol IS NOT NULL AND rol != ''
    """

    connection.execute(sa.text(sql))

    # Para usuarios donde rol es NULL pero role tiene valor, mantener role
    # Para usuarios donde ambos son NULL, poner 'operario'
    connection.execute(sa.text("""
        UPDATE usuarios
        SET role = 'operario'
        WHERE (role IS NULL OR role = '') AND (rol IS NULL OR rol = '')
    """))

    # Actualizar también org_memberships para consistencia
    connection.execute(sa.text("""
        UPDATE org_memberships om
        SET role = u.role
        FROM usuarios u
        WHERE om.user_id = u.id
        AND (om.role IS NULL OR om.role = '' OR om.role = 'operario')
        AND u.role IS NOT NULL AND u.role != ''
    """))


def downgrade():
    """Revertir - copiar role de vuelta a rol."""
    connection = op.get_bind()

    # Mapeo inverso para downgrade
    reverse_mapping = {
        'admin': 'administrador',
        'pm': 'jefe_obra',
        'tecnico': 'tecnico',
        'operario': 'operario',
    }

    case_parts = []
    for new_role, old_role in reverse_mapping.items():
        case_parts.append(f"WHEN LOWER(role) = '{new_role}' THEN '{old_role}'")

    case_statement = " ".join(case_parts)

    sql = f"""
    UPDATE usuarios
    SET rol = CASE
        {case_statement}
        ELSE 'ayudante'
    END
    """

    connection.execute(sa.text(sql))
