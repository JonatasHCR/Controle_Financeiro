"""pis/cofins por contrato

Revision ID: c5a7e19d3f42
Revises: b8e4d2a71c90
Create Date: 2026-10-08 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c5a7e19d3f42'
down_revision = 'b8e4d2a71c90'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'cfg_parametros',
        sa.Column('pis_cofins', sa.Numeric(precision=5, scale=4), nullable=True),
    )


def downgrade():
    op.drop_column('cfg_parametros', 'pis_cofins')
