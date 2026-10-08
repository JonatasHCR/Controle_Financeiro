"""natureza gera credito de pis/cofins

Revision ID: b8e4d2a71c90
Revises: a3c91f0e5b72
Create Date: 2026-10-08 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b8e4d2a71c90'
down_revision = 'a3c91f0e5b72'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('cfg_naturezas_credito',
    sa.Column('natureza_nome_norm', sa.String(length=200), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('atualizado_por_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['atualizado_por_id'], ['tb_usuarios.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('natureza_nome_norm')
    )


def downgrade():
    op.drop_table('cfg_naturezas_credito')
