# FILE: migrations/script.py.mako
# MODULE: Alembic Migration Template for TrueAngels NGO Suite
# Enhanced version with helper functions for common operations

"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma_n}
Create Date: ${create_date}

${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma_n}
Create Date: ${create_date}
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


# ==================== Helper Functions ====================

def create_enum(enum_name: str, values: list, schema: str = None):
    """Helper to create PostgreSQL ENUM types."""
    enum_type = sa.Enum(*values, name=enum_name)
    enum_type.create(op.get_bind(), checkfirst=True)
    if schema:
        op.execute(f'ALTER TYPE {enum_name} SET SCHEMA {schema}')
    return enum_type


def drop_enum(enum_name: str):
    """Helper to drop PostgreSQL ENUM types."""
    op.execute(f'DROP TYPE IF EXISTS {enum_name}')


def create_updated_at_trigger(table_name: str):
    """Helper to create a trigger that updates 'updated_at' column."""
    trigger_name = f"update_{table_name}_updated_at"
    
    op.execute(f"""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    op.execute(f"""
        CREATE TRIGGER {trigger_name}
        BEFORE UPDATE ON {table_name}
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)


def create_partitioned_table(table_name: str, partition_column: str, partition_type: str = "RANGE"):
    """Helper to create partitioned tables (for large datasets)."""
    op.execute(f"""
        CREATE TABLE {table_name}_partitioned (
            LIKE {table_name} INCLUDING DEFAULTS INCLUDING CONSTRAINTS
        ) PARTITION BY {partition_type} ({partition_column});
    """)


def create_partition(parent_table: str, partition_name: str, start_date: str, end_date: str):
    """Helper to create a partition for a date-ranged partitioned table."""
    op.execute(f"""
        CREATE TABLE {partition_name} PARTITION OF {parent_table}
        FOR VALUES FROM ('{start_date}') TO ('{end_date}');
    """)


def enable_rls(table_name: str):
    """Enable Row Level Security on a table."""
    op.execute(f'ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY')


def create_rls_policy(table_name: str, policy_name: str, using_clause: str, with_check_clause: str = None):
    """Helper to create RLS policy."""
    if with_check_clause:
        op.execute(f"""
            CREATE POLICY {policy_name} ON {table_name}
            FOR ALL
            USING ({using_clause})
            WITH CHECK ({with_check_clause});
        """)
    else:
        op.execute(f"""
            CREATE POLICY {policy_name} ON {table_name}
            FOR SELECT
            USING ({using_clause});
        """)


# ==================== Main Migration ====================

def upgrade() -> None:
    """Upgrade database schema to this revision."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade database schema from this revision."""
    ${downgrades if downgrades else "pass"}