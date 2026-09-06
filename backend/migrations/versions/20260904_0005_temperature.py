"""add LLM sampling temperature

Revision ID: 20260904_0005
Revises: 20260903_0004
"""
from alembic import op
import sqlalchemy as sa

revision = "20260904_0005"
down_revision = "20260903_0004"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("provider_configs") as batch:
        batch.add_column(sa.Column("temperature", sa.Float(), nullable=False, server_default="0.7"))

def downgrade() -> None:
    with op.batch_alter_table("provider_configs") as batch:
        batch.drop_column("temperature")
