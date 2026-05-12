"""Add SharedAccess table

Revision ID: b560e0700f8b
Revises: 
Create Date: 2026-05-11 23:47:47.768495

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b560e0700f8b'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # 1. Create the shared_access table
    op.create_table('shared_access',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('guest_token', sa.String(length=20), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=True),
        sa.Column('access_type', sa.String(length=20), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_shared_access'),
        sa.UniqueConstraint('guest_token', name='uq_shared_access_token'),
        sa.ForeignKeyConstraint(['owner_id'], ['authors.id'], name='fk_shared_access_owner')
    )

    # 2. Fix the authors table constraints with explicit names
    with op.batch_alter_table('authors', schema=None) as batch_op:
        batch_op.alter_column('password_hash',
               existing_type=sa.VARCHAR(length=256),
               type_=sa.String(length=200),
               existing_nullable=True)
        batch_op.create_unique_constraint('uq_authors_google_id', ['google_id'])
        batch_op.create_unique_constraint('uq_authors_email', ['email'])

def downgrade():
    with op.batch_alter_table('authors', schema=None) as batch_op:
        batch_op.drop_constraint('uq_authors_email', type_='unique')
        batch_op.drop_constraint('uq_authors_google_id', type_='unique')
        batch_op.alter_column('password_hash',
               existing_type=sa.String(length=200),
               type_=sa.VARCHAR(length=256),
               existing_nullable=True)

    op.drop_table('shared_access')
