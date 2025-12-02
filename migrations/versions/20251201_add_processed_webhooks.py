"""Agregar tabla processed_webhooks para prevención de replay attacks

Revision ID: 20251201_webhooks
Revises: 20251129_unify_role
Create Date: 2025-12-01

Esta migración crea la tabla para trackear webhooks procesados,
previniendo ataques de replay en el sistema de pagos.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251201_webhooks'
down_revision = '20251129_unify_role'
branch_labels = None
depends_on = None


def upgrade():
    """Crear tabla processed_webhooks"""
    op.create_table(
        'processed_webhooks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.String(100), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('processed_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=True),
        sa.Column('payload_hash', sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Índice único para evitar duplicados
    op.create_index(
        'ix_processed_webhooks_request_id',
        'processed_webhooks',
        ['request_id'],
        unique=True
    )

    # Índice para búsqueda por provider
    op.create_index(
        'ix_processed_webhooks_provider',
        'processed_webhooks',
        ['provider']
    )

    # Índice para limpieza de registros antiguos
    op.create_index(
        'ix_processed_webhooks_processed_at',
        'processed_webhooks',
        ['processed_at']
    )


def downgrade():
    """Eliminar tabla processed_webhooks"""
    op.drop_index('ix_processed_webhooks_processed_at', table_name='processed_webhooks')
    op.drop_index('ix_processed_webhooks_provider', table_name='processed_webhooks')
    op.drop_index('ix_processed_webhooks_request_id', table_name='processed_webhooks')
    op.drop_table('processed_webhooks')
