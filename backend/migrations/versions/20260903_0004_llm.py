"""add cloud text assistant persistence

Revision ID: 20260903_0004
Revises: 20260903_0003
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa

revision = "20260903_0004"
down_revision = "20260903_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("provider_configs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider", sa.String(16), nullable=False), sa.Column("name", sa.String(100), nullable=False), sa.Column("base_url", sa.String(300), nullable=False), sa.Column("model", sa.String(100), nullable=False), sa.Column("api_key_encrypted", sa.Text(), nullable=False), sa.Column("api_key_fingerprint", sa.String(64), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("max_output_tokens", sa.Integer(), nullable=False, server_default="2048"), sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="60"), sa.Column("daily_request_limit", sa.Integer(), nullable=False, server_default="100"), sa.Column("validation_fingerprint", sa.String(64)), sa.Column("validated_at", sa.DateTime(timezone=True)), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_table("llm_settings", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("default_provider_config_id", sa.String(36), sa.ForeignKey("provider_configs.id", ondelete="SET NULL")), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_table("provider_call_ledger", sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider_config_id", sa.String(36), sa.ForeignKey("provider_configs.id", ondelete="RESTRICT"), nullable=False), sa.Column("kind", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_provider_call_ledger_provider_config_id", "provider_call_ledger", ["provider_config_id"])
    op.create_table("knowledge_documents", sa.Column("id", sa.String(36), primary_key=True), sa.Column("title", sa.String(100), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])
    op.create_table("knowledge_chunks", sa.Column("id", sa.String(36), primary_key=True), sa.Column("document_id", sa.String(36), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False), sa.Column("document_version", sa.Integer(), nullable=False), sa.Column("chunk_index", sa.Integer(), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("content_sha256", sa.String(64), nullable=False), sa.Column("terms", sa.JSON(), nullable=False), sa.UniqueConstraint("document_id", "document_version", "chunk_index", name="uq_knowledge_chunk_version"))
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_table("assistant_conversations", sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("title", sa.String(100), nullable=False, server_default=""), sa.Column("context_version", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_assistant_conversations_owner_id", "assistant_conversations", ["owner_id"])
    op.create_table("assistant_requests", sa.Column("id", sa.String(36), primary_key=True), sa.Column("conversation_id", sa.String(36), sa.ForeignKey("assistant_conversations.id", ondelete="RESTRICT"), nullable=False), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("mode", sa.String(16), nullable=False), sa.Column("state", sa.String(16), nullable=False, server_default="PREPARED"), sa.Column("provider_config_id", sa.String(36), sa.ForeignKey("provider_configs.id", ondelete="RESTRICT"), nullable=False), sa.Column("provider_version", sa.Integer(), nullable=False), sa.Column("provider", sa.String(16), nullable=False), sa.Column("model", sa.String(100), nullable=False), sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("outbound_payload", sa.JSON(), nullable=False), sa.Column("source_refs", sa.JSON(), nullable=False), sa.Column("conversation_context_version", sa.Integer(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("consented_at", sa.DateTime(timezone=True)), sa.Column("answer", sa.Text()), sa.Column("citations", sa.JSON(), nullable=False), sa.Column("warning_codes", sa.JSON(), nullable=False), sa.Column("usage", sa.JSON()), sa.Column("billing_state", sa.String(16), nullable=False, server_default="NOT_SENT"), sa.Column("provider_request_id", sa.String(128)), sa.Column("error_code", sa.String(64)), sa.Column("is_partial", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_index("ix_assistant_requests_conversation_id", "assistant_requests", ["conversation_id"])
    op.create_index("ix_assistant_requests_owner_id", "assistant_requests", ["owner_id"])
    op.create_index("ix_assistant_requests_state", "assistant_requests", ["state"])
    op.create_index("ix_assistant_requests_payload_hash", "assistant_requests", ["payload_hash"])
    op.create_table("assistant_messages", sa.Column("id", sa.String(36), primary_key=True), sa.Column("request_id", sa.String(36), sa.ForeignKey("assistant_requests.id", ondelete="CASCADE"), nullable=False), sa.Column("conversation_id", sa.String(36), sa.ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False), sa.Column("role", sa.String(12), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("citations", sa.JSON(), nullable=False), sa.Column("source_refs", sa.JSON(), nullable=False), sa.Column("is_partial", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_assistant_messages_request_id", "assistant_messages", ["request_id"])
    op.create_index("ix_assistant_messages_conversation_id", "assistant_messages", ["conversation_id"])


def downgrade() -> None:
    for table, index in (("assistant_messages", "ix_assistant_messages_conversation_id"), ("assistant_messages", "ix_assistant_messages_request_id"), ("assistant_requests", "ix_assistant_requests_payload_hash"), ("assistant_requests", "ix_assistant_requests_state"), ("assistant_requests", "ix_assistant_requests_owner_id"), ("assistant_requests", "ix_assistant_requests_conversation_id"), ("assistant_conversations", "ix_assistant_conversations_owner_id"), ("knowledge_chunks", "ix_knowledge_chunks_document_id"), ("knowledge_documents", "ix_knowledge_documents_status")):
        op.drop_index(index, table_name=table)
    op.drop_table("assistant_messages")
    op.drop_table("assistant_requests")
    op.drop_table("assistant_conversations")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_index("ix_provider_call_ledger_provider_config_id", table_name="provider_call_ledger")
    op.drop_table("provider_call_ledger")
    op.drop_table("llm_settings")
    op.drop_table("provider_configs")
