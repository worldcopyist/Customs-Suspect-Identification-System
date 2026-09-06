"""create internal communication tables

Revision ID: 20260903_0003
Revises: 20260903_0002
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa

revision = "20260903_0003"
down_revision = "20260903_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("conversations", sa.Column("id", sa.String(36), primary_key=True), sa.Column("type", sa.String(12), nullable=False), sa.Column("title", sa.String(100), nullable=False, server_default=""), sa.Column("state", sa.String(12), nullable=False), sa.Column("direct_key", sa.String(73), nullable=True), sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default="0"), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("dissolved_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.UniqueConstraint("direct_key"))
    op.create_index("ix_conversations_direct_key", "conversations", ["direct_key"])
    op.create_index("ix_conversations_created_by", "conversations", ["created_by"])
    op.create_table("conversation_members", sa.Column("id", sa.String(36), primary_key=True), sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("state", sa.String(12), nullable=False), sa.Column("last_read_seq", sa.BigInteger(), nullable=False, server_default="0"), sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("removed_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("conversation_id", "user_id", name="uq_conversation_members_pair"))
    op.create_index("ix_conversation_members_conversation_id", "conversation_members", ["conversation_id"])
    op.create_index("ix_conversation_members_user_id", "conversation_members", ["user_id"])
    op.create_table("chat_messages", sa.Column("id", sa.String(36), primary_key=True), sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False), sa.Column("sender_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("sender_display_name", sa.String(50), nullable=False), sa.Column("seq", sa.BigInteger(), nullable=False), sa.Column("client_message_id", sa.String(36), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.UniqueConstraint("conversation_id", "seq", name="uq_chat_messages_sequence"), sa.UniqueConstraint("conversation_id", "client_message_id", name="uq_chat_messages_client_id"))
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])
    op.create_index("ix_chat_messages_sender_id", "chat_messages", ["sender_id"])
    op.create_table("idempotency_records", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("method", sa.String(10), nullable=False), sa.Column("path", sa.String(300), nullable=False), sa.Column("key", sa.String(36), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("response_status", sa.Integer(), nullable=False), sa.Column("response_data", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.UniqueConstraint("user_id", "method", "path", "key", name="uq_idempotency_scope"))
    op.create_index("ix_idempotency_records_user_id", "idempotency_records", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_user_id", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_chat_messages_sender_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_conversation_members_user_id", table_name="conversation_members")
    op.drop_index("ix_conversation_members_conversation_id", table_name="conversation_members")
    op.drop_table("conversation_members")
    op.drop_index("ix_conversations_created_by", table_name="conversations")
    op.drop_index("ix_conversations_direct_key", table_name="conversations")
    op.drop_table("conversations")
