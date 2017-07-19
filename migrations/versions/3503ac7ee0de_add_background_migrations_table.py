"""Add background migrations table

Revision ID: 3503ac7ee0de
Revises: d378ba47afba
Create Date: 2017-07-17 11:25:37.636106

"""

# revision identifiers, used by Alembic.
revision = '3503ac7ee0de'
down_revision = 'd378ba47afba'

from alembic import op
import sqlalchemy as sa


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('background_migration',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=1024), nullable=False),
    sa.Column('started', sa.Boolean(), server_default='FALSE', nullable=True),
    sa.Column('started_time', sa.Float(), nullable=True),
    sa.Column('finished', sa.Boolean(), server_default='FALSE', nullable=True),
    sa.Column('finished_time', sa.Float(), nullable=True),
    sa.Column('total_num_objects', sa.Integer(), nullable=True),
    sa.Column('remaining_num_objects', sa.Integer(), nullable=True),
    sa.Column('update_query', sa.Text(), nullable=False),
    sa.Column('remaining_num_items_query', sa.Text(), nullable=False),
    sa.Column('batch_size', sa.Integer(), server_default='100000', nullable=False),
    sa.CheckConstraint("update_query like '%\\:batch_size%'", name='check_has_batch_size'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_background_migration_finished'), 'background_migration', ['finished'], unique=False)
    op.create_index(op.f('ix_background_migration_started'), 'background_migration', ['started'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_background_migration_started'), table_name='background_migration')
    op.drop_index(op.f('ix_background_migration_finished'), table_name='background_migration')
    op.drop_table('background_migration')
    # ### end Alembic commands ###