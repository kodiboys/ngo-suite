-- FILE: migrations/versions/002_add_transparency_and_needs.py
-- MODULE: Migration für Transparenz-Features & Bedarfe

"""Add transparency and project needs tables

Revision ID: 002
Revises: 001
Create Date: 2024-01-15 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1. Add consent_transparenz to donations
    op.add_column('donations', sa.Column(
        'consent_transparenz', 
        sa.Boolean, 
        server_default='false', 
        nullable=False
    ))
    op.add_column('donations', sa.Column(
        'transparency_hash', 
        sa.String(20), 
        nullable=True
    ))
    op.create_index(
        'idx_donations_transparency_hash', 
        'donations', 
        ['transparency_hash']
    )
    
    # 2. Create project_needs table
    op.create_table(
        'project_needs',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('project_id', UUID(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('priority', sa.String(20), nullable=False),
        sa.Column('quantity_target', sa.Integer(), nullable=False),
        sa.Column('quantity_current', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unit', sa.String(20), nullable=True),
        sa.Column('unit_price_eur', sa.Numeric(10, 2), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', UUID(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_needs_project', 'project_needs', ['project_id'])
    op.create_index('idx_needs_category', 'project_needs', ['category'])
    op.create_index('idx_needs_priority', 'project_needs', ['priority'])
    
    # 3. Create transparency_hashes table (Merkle-Tree)
    op.create_table(
        'transparency_hashes',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('merkle_root', sa.String(64), nullable=False),
        sa.Column('previous_root', sa.String(64), nullable=True),
        sa.Column('record_count', sa.Integer(), nullable=False),
        sa.Column('verified_by', UUID(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['verified_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date', name='uq_transparency_date')
    )
    op.create_index('idx_transparency_year_month', 'transparency_hashes', ['year', 'month'])
    
    # 4. Add needs_alert_config to projects
    op.add_column('projects', sa.Column(
        'needs_alert_config', 
        JSONB, 
        server_default='{"enabled": true, "threshold_percent": 20, "channels": ["email"]}',
        nullable=False
    ))

def downgrade() -> None:
    op.drop_table('transparency_hashes')
    op.drop_table('project_needs')
    op.drop_index('idx_donations_transparency_hash', table_name='donations')
    op.drop_column('donations', 'transparency_hash')
    op.drop_column('donations', 'consent_transparenz')
    op.drop_column('projects', 'needs_alert_config')