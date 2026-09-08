"""V1.3 JWT session revision; invalidates V1.2 opaque sessions without data reset.

Revision ID: 20260908_0007
Revises: 20260905_0006
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa


revision = "20260908_0007"
down_revision = "20260905_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("auth_sessions", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))
    # V1.2 opaque browser tokens are intentionally not translated into JWTs.
    # Password hashes, accounts, provider keys and business data remain intact.
    op.execute("UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE revoked_at IS NULL")


def downgrade() -> None:
    raise RuntimeError("JWT migration invalidates browser sessions; restore a verified backup to downgrade")
