"""mock exam pause

Revision ID: a3c91f0e7b42
Revises: 57bfe183e3d1
Create Date: 2026-10-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3c91f0e7b42'
down_revision = '57bfe183e3d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mock_exams', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pause_count', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('mock_exam_sections', schema=None) as batch_op:
        batch_op.add_column(sa.Column('paused_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('paused_seconds', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    with op.batch_alter_table('mock_exam_sections', schema=None) as batch_op:
        batch_op.drop_column('paused_seconds')
        batch_op.drop_column('paused_at')

    with op.batch_alter_table('mock_exams', schema=None) as batch_op:
        batch_op.drop_column('pause_count')
