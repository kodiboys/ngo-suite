# FILE: migrations/versions/004_update_inventory_for_needs.py
# MODULE: Migration für Inventory-Erweiterungen (v3.0)

"""Update inventory for needs

Revision ID: 004
Revises: 003
Create Date: 2024-01-21 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add need_id to inventory_items
    op.add_column('inventory_items', sa.Column(
        'need_id', 
        sa.UUID(), 
        nullable=True
    ))
    op.create_foreign_key(
        'fk_inventory_items_need_id',
        'inventory_items', 'project_needs',
        ['need_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_index('idx_inventory_items_need_id', 'inventory_items', ['need_id'])
    
    # Add reserved_for_need to inventory_items
    op.add_column('inventory_items', sa.Column(
        'reserved_for_need', 
        sa.Integer(), 
        nullable=False, 
        server_default='0'
    ))
    
    # Add last_need_fulfillment_at to inventory_items
    op.add_column('inventory_items', sa.Column(
        'last_need_fulfillment_at', 
        sa.DateTime(), 
        nullable=True
    ))
    
    # Add need_fulfillment_count to inventory_items
    op.add_column('inventory_items', sa.Column(
        'need_fulfillment_count', 
        sa.Integer(), 
        nullable=False, 
        server_default='0'
    ))
    
    # Add show_on_transparency to inventory_items
    op.add_column('inventory_items', sa.Column(
        'show_on_transparency', 
        sa.Boolean(), 
        nullable=False, 
        server_default='true'
    ))
    
    # Add need_id to stock_movements
    op.add_column('stock_movements', sa.Column(
        'need_id', 
        sa.UUID(), 
        nullable=True
    ))
    op.create_foreign_key(
        'fk_stock_movements_need_id',
        'stock_movements', 'project_needs',
        ['need_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_index('idx_stock_movements_need_id', 'stock_movements', ['need_id'])
    
    # Add need_fulfillment_id to stock_movements
    op.add_column('stock_movements', sa.Column(
        'need_fulfillment_id', 
        sa.UUID(), 
        nullable=True
    ))
    op.create_index('idx_stock_movements_need_fulfillment', 'stock_movements', ['need_fulfillment_id'])
    
    # Add need_ids to packing_lists (JSONB)
    op.add_column('packing_lists', sa.Column(
        'need_ids', 
        JSONB(), 
        nullable=True,
        server_default='[]'
    ))
    
    # Add transparency_hash to packing_lists
    op.add_column('packing_lists', sa.Column(
        'transparency_hash', 
        sa.String(50), 
        nullable=True
    ))
    op.create_index('idx_packing_lists_transparency', 'packing_lists', ['transparency_hash'])
    
    # Add show_on_transparency to packing_lists
    op.add_column('packing_lists', sa.Column(
        'show_on_transparency', 
        sa.Boolean(), 
        nullable=False, 
        server_default='true'
    ))
    
    # Add need_id to packing_list_items
    op.add_column('packing_list_items', sa.Column(
        'need_id', 
        sa.UUID(), 
        nullable=True
    ))
    op.create_foreign_key(
        'fk_packing_list_items_need_id',
        'packing_list_items', 'project_needs',
        ['need_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_index('idx_packing_list_items_need_id', 'packing_list_items', ['need_id'])

def downgrade() -> None:
    op.drop_index('idx_packing_list_items_need_id', table_name='packing_list_items')
    op.drop_constraint('fk_packing_list_items_need_id', 'packing_list_items', type_='foreignkey')
    op.drop_column('packing_list_items', 'need_id')
    
    op.drop_index('idx_packing_lists_transparency', table_name='packing_lists')
    op.drop_column('packing_lists', 'show_on_transparency')
    op.drop_column('packing_lists', 'transparency_hash')
    op.drop_column('packing_lists', 'need_ids')
    
    op.drop_index('idx_stock_movements_need_fulfillment', table_name='stock_movements')
    op.drop_column('stock_movements', 'need_fulfillment_id')
    
    op.drop_index('idx_stock_movements_need_id', table_name='stock_movements')
    op.drop_constraint('fk_stock_movements_need_id', 'stock_movements', type_='foreignkey')
    op.drop_column('stock_movements', 'need_id')
    
    op.drop_column('inventory_items', 'show_on_transparency')
    op.drop_column('inventory_items', 'need_fulfillment_count')
    op.drop_column('inventory_items', 'last_need_fulfillment_at')
    op.drop_column('inventory_items', 'reserved_for_need')
    op.drop_index('idx_inventory_items_need_id', table_name='inventory_items')
    op.drop_constraint('fk_inventory_items_need_id', 'inventory_items', type_='foreignkey')
    op.drop_column('inventory_items', 'need_id')