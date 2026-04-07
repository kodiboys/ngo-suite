# FILE: migrations/versions/001_initial_schema.py
# MODULE: Initial Database Schema Migration
# Erstellt alle Core-Tabellen für die TrueAngels NGO Suite v3.0.0
# Revision ID: 001
# Revises: None
# Create Date: 2024-01-15 10:00:00.000000

"""
Initial schema for TrueAngels NGO Suite

This migration creates the core database tables for:
- Users & Authentication
- Projects & SKR42 Accounts
- Donations & Transactions
- Audit Logs
- Event Store for Event Sourcing
- Compliance Tables (Four Eyes, Money Laundering)
- Transparency Tables

Revision ID: 001
Revises: None
Create Date: 2024-01-15 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all initial tables"""
    
    # ==================== Enable Extensions ====================
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"')
    
    # ==================== SKR42 Accounts Table ====================
    op.create_table(
        'skr42_accounts',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('account_number', sa.String(5), nullable=False),
        sa.Column('account_name', sa.String(200), nullable=False),
        sa.Column('account_type', sa.String(50), nullable=False),
        sa.Column('cost_center', sa.String(50), nullable=True),
        sa.Column('project_id', UUID(), nullable=True),
        sa.Column('parent_account_number', sa.String(5), nullable=True),
        sa.Column('level', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('requires_four_eyes', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('tax_code', sa.String(10), nullable=True),
        sa.Column('show_in_transparency', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('transparency_description', sa.Text(), nullable=True),
        sa.Column('previous_hash', sa.String(64), nullable=True),
        sa.Column('current_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['parent_account_number'], ['skr42_accounts.account_number'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_number', 'cost_center', name='uq_account_costcenter'),
        sa.CheckConstraint("account_number BETWEEN '10000' AND '99999'", name='ck_valid_account')
    )
    op.create_index('idx_account_number_costcenter', 'skr42_accounts', ['account_number', 'cost_center'])
    
    # ==================== Users Table ====================
    op.create_table(
        'users',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('email_verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('name_encrypted', sa.Text(), nullable=True),
        sa.Column('phone_encrypted', sa.Text(), nullable=True),
        sa.Column('role', sa.String(50), nullable=False, server_default='donor'),
        sa.Column('permissions', JSONB(), nullable=True),
        sa.Column('mfa_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('mfa_secret', sa.String(255), nullable=True),
        sa.Column('telegram_chat_id', sa.String(100), nullable=True),
        sa.Column('notification_preferences', JSONB(), nullable=True),
        sa.Column('consent_given_at', sa.DateTime(), nullable=True),
        sa.Column('consent_withdrawn_at', sa.DateTime(), nullable=True),
        sa.Column('is_pseudonymized', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('last_login_ip', sa.String(45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index('idx_users_email', 'users', ['email'])
    op.create_index('idx_users_role', 'users', ['role'])
    
    # ==================== Projects Table ====================
    op.create_table(
        'projects',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('transparency_description', sa.Text(), nullable=True),
        sa.Column('image_url', sa.String(500), nullable=True),
        sa.Column('show_on_transparency', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('cost_center', sa.String(50), nullable=False),
        sa.Column('skr42_account_id', UUID(), nullable=False),
        sa.Column('budget_total', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('budget_used', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('donations_total', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('start_date', sa.DateTime(), nullable=False),
        sa.Column('end_date', sa.DateTime(), nullable=True),
        sa.Column('requires_four_eyes', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('needs_alert_config', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['skr42_account_id'], ['skr42_accounts.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cost_center')
    )
    op.create_index('idx_projects_status', 'projects', ['status'])
    op.create_index('idx_projects_cost_center', 'projects', ['cost_center'])
    
    # ==================== Donations Table ====================
    op.create_table(
        'donations',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('donor_email_pseudonym', sa.String(255), nullable=False),
        sa.Column('donor_name_encrypted', sa.Text(), nullable=True),
        sa.Column('donor_address_encrypted', sa.Text(), nullable=True),
        sa.Column('project_id', UUID(), nullable=False),
        sa.Column('skr42_account_id', UUID(), nullable=False),
        sa.Column('cost_center', sa.String(50), nullable=False),
        sa.Column('need_id', UUID(), nullable=True),
        sa.Column('consent_transparenz', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('transparency_hash', sa.String(20), nullable=True),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('transaction_type', sa.String(50), nullable=False, server_default='spende'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='EUR'),
        sa.Column('payment_provider', sa.String(20), nullable=False),
        sa.Column('payment_intent_id', sa.String(255), nullable=False),
        sa.Column('payment_status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('compliance_status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('four_eyes_approved_by', UUID(), nullable=True),
        sa.Column('four_eyes_approved_at', sa.DateTime(), nullable=True),
        sa.Column('money_laundering_flag', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('tax_deductible', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('tax_id', sa.String(20), nullable=True),
        sa.Column('donation_receipt_generated', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('previous_hash', sa.String(64), nullable=True),
        sa.Column('current_hash', sa.String(64), nullable=False),
        sa.Column('blockchain_tx_id', sa.String(255), nullable=True),
        sa.Column('is_pseudonymized', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('pseudonymized_at', sa.DateTime(), nullable=True),
        sa.Column('deletion_requested_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['four_eyes_approved_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['need_id'], ['project_needs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['skr42_account_id'], ['skr42_accounts.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('payment_intent_id')
    )
    op.create_index('idx_donor_email_pseudonym', 'donations', ['donor_email_pseudonym'])
    op.create_index('idx_project_status', 'donations', ['project_id', 'payment_status'])
    op.create_index('idx_compliance_flag', 'donations', ['compliance_status'])
    op.create_index('idx_transparency_hash', 'donations', ['transparency_hash'])
    op.create_index('idx_consent_transparenz', 'donations', ['consent_transparenz'])
    
    # ==================== Audit Logs Table ====================
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', UUID(), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', UUID(), nullable=False),
        sa.Column('old_values', JSONB(), nullable=True),
        sa.Column('new_values', JSONB(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=False),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('requires_four_eyes', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('four_eyes_approved', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('four_eyes_by', UUID(), nullable=True),
        sa.Column('retention_until', sa.DateTime(), nullable=False),
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['four_eyes_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_entity_timestamp', 'audit_logs', ['entity_type', 'entity_id', 'timestamp'])
    op.create_index('idx_user_action', 'audit_logs', ['user_id', 'action'])
    
    # ==================== Event Store Table ====================
    op.create_table(
        'event_store',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_id', UUID(), nullable=False),
        sa.Column('aggregate_id', UUID(), nullable=False),
        sa.Column('aggregate_type', sa.String(100), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_version', sa.String(20), nullable=False, server_default='1.0'),
        sa.Column('sequence_number', sa.Integer(), nullable=False),
        sa.Column('data', JSONB(), nullable=False),
        sa.Column('metadata', JSONB(), nullable=True),
        sa.Column('user_id', UUID(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('previous_hash', sa.String(64), nullable=True),
        sa.Column('current_hash', sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id'),
        sa.UniqueConstraint('aggregate_id', 'sequence_number', name='uq_event_sequence')
    )
    op.create_index('idx_event_aggregate', 'event_store', ['aggregate_id', 'sequence_number'])
    op.create_index('idx_event_type_time', 'event_store', ['event_type', 'timestamp'])
    op.create_index('idx_event_hash', 'event_store', ['current_hash'])
    
    # ==================== Four Eyes Approvals Table ====================
    op.create_table(
        'four_eyes_approvals',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', UUID(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='EUR'),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('initiator_id', UUID(), nullable=False),
        sa.Column('initiated_at', sa.DateTime(), nullable=False),
        sa.Column('approver_1_id', UUID(), nullable=False),
        sa.Column('approver_1_approved_at', sa.DateTime(), nullable=True),
        sa.Column('approver_1_comment', sa.Text(), nullable=True),
        sa.Column('approver_1_ip', sa.String(45), nullable=True),
        sa.Column('approver_2_id', UUID(), nullable=True),
        sa.Column('approver_2_approved_at', sa.DateTime(), nullable=True),
        sa.Column('approver_2_comment', sa.Text(), nullable=True),
        sa.Column('approver_2_ip', sa.String(45), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('escalated_to', UUID(), nullable=True),
        sa.Column('escalated_at', sa.DateTime(), nullable=True),
        sa.Column('escalation_reason', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('reminded_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['approver_1_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['approver_2_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['escalated_to'], ['users.id'], ),
        sa.ForeignKeyConstraint(['initiator_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_foureyes_entity', 'four_eyes_approvals', ['entity_type', 'entity_id'])
    op.create_index('idx_foureyes_status', 'four_eyes_approvals', ['status'])
    op.create_index('idx_foureyes_approvers', 'four_eyes_approvals', ['approver_1_id', 'approver_2_id'])
    
    # ==================== Money Laundering Checks Table ====================
    op.create_table(
        'money_laundering_checks',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', UUID(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='EUR'),
        sa.Column('donor_name', sa.String(200), nullable=True),
        sa.Column('donor_email', sa.String(255), nullable=True),
        sa.Column('donor_country', sa.String(2), nullable=True),
        sa.Column('payment_method', sa.String(50), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('device_fingerprint', sa.String(255), nullable=True),
        sa.Column('risk_level', sa.String(50), nullable=False),
        sa.Column('risk_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('checks_performed', JSONB(), nullable=True),
        sa.Column('flags', JSONB(), nullable=True),
        sa.Column('sanctions_list_hit', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sanctions_list_name', sa.String(200), nullable=True),
        sa.Column('pep_check_passed', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('adverse_media_found', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('reported_to_fiu', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('reported_at', sa.DateTime(), nullable=True),
        sa.Column('report_reference', sa.String(100), nullable=True),
        sa.Column('report_data', JSONB(), nullable=True),
        sa.Column('compliance_result', sa.String(50), nullable=False),
        sa.Column('reviewed_by', UUID(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_ml_entity', 'money_laundering_checks', ['entity_type', 'entity_id'])
    op.create_index('idx_ml_risk_level', 'money_laundering_checks', ['risk_level'])
    op.create_index('idx_ml_reported', 'money_laundering_checks', ['reported_to_fiu'])
    
    # ==================== GoBD Compliance Records Table ====================
    op.create_table(
        'gobd_compliance_records',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('record_type', sa.String(50), nullable=False),
        sa.Column('record_id', UUID(), nullable=False),
        sa.Column('record_hash', sa.String(64), nullable=False),
        sa.Column('retention_period_years', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('retention_until', sa.DateTime(), nullable=False),
        sa.Column('storage_location', sa.String(500), nullable=True),
        sa.Column('original_filename', sa.String(255), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(100), nullable=True),
        sa.Column('encrypted', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('encryption_key_id', sa.String(100), nullable=True),
        sa.Column('access_log', JSONB(), nullable=True),
        sa.Column('deletion_protected_until', sa.DateTime(), nullable=False),
        sa.Column('deletion_requested', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deletion_requested_at', sa.DateTime(), nullable=True),
        sa.Column('deletion_approved_by', UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', UUID(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['deletion_approved_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_gobd_record_type', 'gobd_compliance_records', ['record_type', 'record_id'])
    op.create_index('idx_gobd_retention_date', 'gobd_compliance_records', ['retention_until'])
    
    # ==================== Compliance Alerts Table ====================
    op.create_table(
        'compliance_alerts',
        sa.Column('id', UUID(), nullable=False),
        sa.Column('alert_type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('priority', sa.String(20), nullable=False, server_default='medium'),
        sa.Column('severity_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', UUID(), nullable=True),
        sa.Column('assigned_to', UUID(), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_by', UUID(), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.Column('escalated_at', sa.DateTime(), nullable=True),
        sa.Column('escalation_level', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notified_users', JSONB(), nullable=True),
        sa.Column('last_notification_at', sa.DateTime(), nullable=True),
        sa.Column('response_deadline', sa.DateTime(), nullable=False),
        sa.Column('reminded_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', UUID(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_alert_status', 'compliance_alerts', ['status'])
    op.create_index('idx_alert_priority', 'compliance_alerts', ['priority'])
    op.create_index('idx_alert_assignee', 'compliance_alerts', ['assigned_to'])
    
    # ==================== Row Level Security Policies ====================
    # Enable RLS on critical tables
    op.execute('ALTER TABLE donations ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE users ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE projects ENABLE ROW LEVEL SECURITY')
    
    # Create RLS policies
    op.execute("""
        CREATE POLICY donor_select_policy ON donations
            FOR SELECT USING (
                donor_email_pseudonym = current_setting('app.current_donor_email')::text
                AND is_pseudonymized = true
            )
    """)
    
    op.execute("""
        CREATE POLICY admin_all_policy ON donations
            FOR ALL USING (
                current_setting('app.current_user_role') = 'admin'
            )
    """)
    
    op.execute("""
        CREATE POLICY accountant_select_policy ON donations
            FOR SELECT USING (
                current_setting('app.current_user_role') = 'accountant'
            )
            WITH CHECK (false)
    """)
    
    op.execute("""
        CREATE POLICY four_eyes_policy ON donations
            FOR UPDATE USING (
                amount > 5000 
                AND current_setting('app.four_eyes_approved') = 'true'
            )
    """)
    
    op.execute("""
        CREATE POLICY transparency_select_policy ON donations
            FOR SELECT USING (
                consent_transparenz = true
                AND payment_status = 'succeeded'
            )
    """)


def downgrade() -> None:
    """Drop all tables in reverse order"""
    
    # Drop RLS policies
    op.execute('DROP POLICY IF EXISTS donor_select_policy ON donations')
    op.execute('DROP POLICY IF EXISTS admin_all_policy ON donations')
    op.execute('DROP POLICY IF EXISTS accountant_select_policy ON donations')
    op.execute('DROP POLICY IF EXISTS four_eyes_policy ON donations')
    op.execute('DROP POLICY IF EXISTS transparency_select_policy ON donations')
    
    # Disable RLS
    op.execute('ALTER TABLE donations DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE users DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE projects DISABLE ROW LEVEL SECURITY')
    
    # Drop tables in reverse order
    op.drop_table('compliance_alerts')
    op.drop_table('gobd_compliance_records')
    op.drop_table('money_laundering_checks')
    op.drop_table('four_eyes_approvals')
    op.drop_table('event_store')
    op.drop_table('audit_logs')
    op.drop_table('donations')
    op.drop_table('projects')
    op.drop_table('users')
    op.drop_table('skr42_accounts')
    
    # Drop extensions (optional, comment if needed)
    # op.execute('DROP EXTENSION IF EXISTS "pg_stat_statements"')
    # op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
#```
#
#---
#
## 📋 **MIGRATION ÜBERSICHT**
#
#| Tabelle                           | Zweck |
#|-----------------------------------|---------------------------------------------------|
#| `skr42_accounts`                  | SKR42 Kontenrahmen mit Kostenträgern              |
#| `users`                           | Benutzer mit RBAC, MFA, Benachrichtigungen        |
#| `projects`                        | Projekte mit Budget, Fortschritt, Transparenz     |
#| `donations`                       | Spenden mit Compliance, Pseudonymisierung, SKR42  |
#| `audit_logs`                      | DSGVO/GoBD konformes Audit-Log                    |
#| `event_store`                     | Event Sourcing (Greg Young Pattern)               |
#| `four_eyes_approvals`             | 4-Augen-Prinzip Workflow                          |
#| `money_laundering_checks`         | Geldwäscheprüfungen                               |
#| `gobd_compliance_records`         | GoBD-revisionssichere Aufbewahrung                |
#| `compliance_alerts`               | Compliance-Benachrichtigungen                     |
#
#---
#
#**Die initiale Migration ist vollständig und bereit für die Ausführung!**