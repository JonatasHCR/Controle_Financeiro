"""contrato desativado na receita

Revision ID: a3c91f0e5b72
Revises: d7ec8a58b23d
Create Date: 2026-10-07 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a3c91f0e5b72'
down_revision = 'd7ec8a58b23d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'rc_contratos',
        sa.Column('ativo', sa.Boolean(), server_default='true', nullable=False),
    )


def downgrade():
    op.drop_column('rc_contratos', 'ativo')
