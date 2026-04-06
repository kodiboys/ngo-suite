# FILE: migrations/versions/003_add_project_needs.py
# MODULE: Migration für Project Needs Tabelle

"""Add project_needs table

Revision ID: 003
Revises: 002
Create Date: 2024-01-20 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create project_needs table
    op.create_table(
        'project_needs',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('project_id', UUID(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(50), nullable=False, server_default='sonstige'),
        sa.Column('priority', sa.String(20), nullable=False, server_default='medium'),
        sa.Column('quantity_target', sa.Integer(), nullable=False),
        sa.Column('quantity_current', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unit', sa.String(20), nullable=True, server_default='Stück'),
        sa.Column('unit_price_eur', sa.Numeric(10, 2), nullable=True),
        sa.Column('total_value_eur', sa.Numeric(12, 2), nullable=True),
        sa.Column('inventory_item_id', UUID(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('fulfillment_percentage', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('valid_from', sa.DateTime(), nullable=True),
        sa.Column('valid_until', sa.DateTime(), nullable=True),
        sa.Column('alert_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('alert_threshold_percent', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('alert_channels', JSONB(), nullable=True),
        sa.Column('last_alert_sent_at', sa.DateTime(), nullable=True),
        sa.Column('images', JSONB(), nullable=True),
        sa.Column('documents', JSONB(), nullable=True),
        sa.Column('tags', JSONB(), nullable=True),
        sa.Column('custom_fields', JSONB(), nullable=True),
        sa.Column('created_by', UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('fulfilled_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['inventory_item_id'], ['inventory_items.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'name', name='uq_need_per_project')
    )
    
    # Create indexes
    op.create_index('idx_needs_project', 'project_needs', ['project_id'])
    op.create_index('idx_needs_category', 'project_needs', ['category'])
    op.create_index('idx_needs_priority', 'project_needs', ['priority'])
    op.create_index('idx_needs_status', 'project_needs', ['status'])
    op.create_index('idx_needs_fulfillment', 'project_needs', ['fulfillment_percentage'])
    
    # Create need_history table
    op.create_table(
        'need_history',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('need_id', UUID(), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('old_values', JSONB(), nullable=True),
        sa.Column('new_values', JSONB(), nullable=True),
        sa.Column('change_reason', sa.Text(), nullable=True),
        sa.Column('changed_by', UUID(), nullable=False),
        sa.Column('source_type', sa.String(50), nullable=False, server_default='manual'),
        sa.Column('source_id', UUID(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['changed_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['need_id'], ['project_needs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_need_history_need', 'need_history', ['need_id'])
    op.create_index('idx_need_history_timestamp', 'need_history', ['timestamp'])
    
    # Create need_alert_logs table
    op.create_table(
        'need_alert_logs',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('need_id', UUID(), nullable=False),
        sa.Column('channel', sa.String(50), nullable=False),
        sa.Column('recipient', sa.String(500), nullable=False),
        sa.Column('subject', sa.String(500), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='sent'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['need_id'], ['project_needs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_alert_need', 'need_alert_logs', ['need_id'])
    op.create_index('idx_alert_channel', 'need_alert_logs', ['channel'])
    op.create_index('idx_alert_sent_at', 'need_alert_logs', ['sent_at'])
    
    # Add needs_alert_config to projects
    op.add_column('projects', sa.Column(
        'needs_alert_config',
        JSONB,
        server_default='{"enabled": true, "default_threshold_percent": 20, "default_channels": ["email"]}',
        nullable=True
    ))

def downgrade() -> None:
    op.drop_table('need_alert_logs')
    op.drop_table('need_history')
    op.drop_table('project_needs')
    op.drop_column('projects', 'needs_alert_config')