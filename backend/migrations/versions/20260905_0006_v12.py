"""V1.2 additive migration; preserves accounts, source media and message history."""
from alembic import op
import sqlalchemy as sa

revision = "20260905_0006"
down_revision = "20260904_0005"
branch_labels = depends_on = None

def upgrade():
    from app.models.extension import Person, DetectionBatch, DetectionHistory, AgentProfile, OperationLog
    for entity in (Person, DetectionBatch, DetectionHistory, AgentProfile, OperationLog):
        entity.__table__.create(op.get_bind(), checkfirst=True)
    fields = {
        "auth_sessions": [sa.Column("presence_at", sa.DateTime(timezone=True))],
        "media": [sa.Column("upload_byte_size", sa.Integer(), nullable=False, server_default="0")],
        "detections": [sa.Column("rendered_media_id", sa.String(36)), sa.Column("batch_id", sa.String(36)), sa.Column("batch_index", sa.Integer()), sa.Column("deleted_at", sa.DateTime(timezone=True)), sa.Column("warning_codes", sa.JSON(), nullable=False, server_default="[]")],
        "detection_boxes": [sa.Column("person_link", sa.JSON())],
        "camera_sessions": [sa.Column("generation", sa.Integer(), nullable=False, server_default="1"), sa.Column("capture_interval_ms", sa.Integer(), nullable=False, server_default="500")],
        "provider_configs": [sa.Column("capabilities", sa.JSON())],
        "llm_settings": [sa.Column("default_agent_profile_id", sa.String(36))],
        "assistant_requests": [sa.Column("agent_profile_id", sa.String(36)), sa.Column("agent_version", sa.Integer()), sa.Column("agent_name_snapshot", sa.String(100)), sa.Column("prompt_template_version", sa.String(64), nullable=False, server_default="customs-text-v2"), sa.Column("delivery_mode", sa.String(32), nullable=False, server_default="BUFFERED_FINAL")],
    }
    for table, columns in fields.items():
        for column in columns:
            op.add_column(table, column)
    op.execute("UPDATE media SET upload_byte_size=byte_size")
    op.create_index("uq_single_public_room", "conversations", ["type"], unique=True, sqlite_where=sa.text("type='PUBLIC'"))
    op.create_index("uq_active_user_batch", "detection_batches", ["owner_id"], unique=True, sqlite_where=sa.text("state='RUNNING'"))
    op.execute("INSERT INTO conversations (id,type,title,state,last_seq,version) VALUES ('00000000-0000-4000-8000-000000000001','PUBLIC','公共聊天室','ACTIVE',0,1)")
    # Old provider-only previews cannot silently become a different role.
    op.execute("UPDATE assistant_requests SET state='EXPIRED', error_code='CONTEXT_CHANGED' WHERE state='PREPARED'")
    bind = op.get_bind()
    from uuid import uuid4
    for provider in bind.execute(sa.text("SELECT id,name,temperature FROM provider_configs")).mappings():
        agent_id = str(uuid4())
        bind.execute(sa.text("INSERT INTO agent_profiles (id,name,description,business_prompt,temperature,provider_config_id,status,version) VALUES (:id,:name,'迁移配置；请测试厂商能力后启用','提供课程实训文本帮助，不推断人员身份。',:temperature,:provider,'INACTIVE',1)"), {"id":agent_id,"name":provider["name"],"temperature":provider["temperature"],"provider":provider["id"]})
        bind.execute(sa.text("UPDATE llm_settings SET default_agent_profile_id=:agent WHERE default_provider_config_id=:provider"), {"agent":agent_id,"provider":provider["id"]})

def downgrade():
    raise RuntimeError("V1.2 contains durable user data; restore a verified backup to downgrade")
