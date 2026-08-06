"""add persisted runtime settings

Revision ID: 0003_runtime_settings
Revises: 0002_search_profiles
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_runtime_settings"
down_revision = "0002_search_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("runtime_settings")
