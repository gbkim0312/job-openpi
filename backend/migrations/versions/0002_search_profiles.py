"""add editable search profiles

Revision ID: 0002_search_profiles
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_search_profiles"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "search_profiles",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("search_profiles")
