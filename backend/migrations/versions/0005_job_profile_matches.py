"""track profile-to-job matches

Revision ID: 0005_job_profile_matches
Revises: 0004_job_filter_fields
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_job_profile_matches"
down_revision = "0004_job_filter_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_profile_matches",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("job_postings.id"), primary_key=True),
        sa.Column("profile_id", sa.String(length=100), primary_key=True),
        sa.Column("matched_query", sa.Text(), nullable=False, server_default=""),
        sa.Column("first_matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_matched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_job_profile_matches_profile_id",
        "job_profile_matches",
        ["profile_id"],
    )


def downgrade():
    op.drop_index("ix_job_profile_matches_profile_id", table_name="job_profile_matches")
    op.drop_table("job_profile_matches")
