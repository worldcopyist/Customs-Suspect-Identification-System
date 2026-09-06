"""add controlled media, detection and camera-session tables

Revision ID: 20260903_0002
Revises: 20260903_0001
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260903_0002"
down_revision = "20260903_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("mime_type", sa.String(length=32), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("storage_key", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_media_owner_id", "media", ["owner_id"])
    op.create_index("ix_media_sha256", "media", ["sha256"])
    op.create_table(
        "detections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("review_status", sa.String(length=24), nullable=False),
        sa.Column("model_id", sa.String(length=64)),
        sa.Column("model_sha256", sa.String(length=64)),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_media_id", sa.String(length=36)),
        sa.Column("image_width", sa.Integer()),
        sa.Column("image_height", sa.Integer()),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_media_id"], ["media.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_detections_owner_id", "detections", ["owner_id"])
    op.create_index("ix_detections_state", "detections", ["state"])
    op.create_index("ix_detections_source_media_id", "detections", ["source_media_id"])
    op.create_table(
        "detection_boxes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("detection_id", sa.String(length=36), nullable=False),
        sa.Column("box_index", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("class_name", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["detection_id"], ["detections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("detection_id", "box_index", name="uq_detection_box_index"),
    )
    op.create_index("ix_detection_boxes_detection_id", "detection_boxes", ["detection_id"])
    op.create_table(
        "camera_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("client_label", sa.String(length=100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_camera_sessions_owner_id", "camera_sessions", ["owner_id"])
    op.create_index("ix_camera_sessions_state", "camera_sessions", ["state"])


def downgrade() -> None:
    op.drop_index("ix_camera_sessions_state", table_name="camera_sessions")
    op.drop_index("ix_camera_sessions_owner_id", table_name="camera_sessions")
    op.drop_table("camera_sessions")
    op.drop_index("ix_detection_boxes_detection_id", table_name="detection_boxes")
    op.drop_table("detection_boxes")
    op.drop_index("ix_detections_source_media_id", table_name="detections")
    op.drop_index("ix_detections_state", table_name="detections")
    op.drop_index("ix_detections_owner_id", table_name="detections")
    op.drop_table("detections")
    op.drop_index("ix_media_sha256", table_name="media")
    op.drop_index("ix_media_owner_id", table_name="media")
    op.drop_table("media")
