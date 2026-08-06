"""add normalized experience filter field

Revision ID: 0004_job_filter_fields
Revises: 0003_runtime_settings
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_job_filter_fields"
down_revision = "0003_runtime_settings"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    column_names = {column["name"] for column in inspector.get_columns("job_postings")}
    if "experience_type" not in column_names:
        op.add_column(
            "job_postings",
            sa.Column(
                "experience_type", sa.String(length=20), nullable=False, server_default="UNKNOWN"
            ),
        )
    index_names = {index["name"] for index in inspector.get_indexes("job_postings")}
    if "ix_job_postings_experience_type" not in index_names:
        op.create_index("ix_job_postings_experience_type", "job_postings", ["experience_type"])
    op.execute(
        """
        UPDATE job_postings
        SET experience_type = CASE
            WHEN lower(coalesce(experience_raw, '')) LIKE '%신입%'
                 AND lower(coalesce(experience_raw, '')) NOT LIKE '%경력%' THEN 'NEWBIE'
            WHEN lower(coalesce(experience_raw, '')) LIKE '%신입%'
                 AND lower(coalesce(experience_raw, '')) LIKE '%경력%' THEN 'ANY'
            WHEN lower(coalesce(experience_raw, '')) LIKE '%경력%'
                 OR min_experience_years IS NOT NULL THEN 'EXPERIENCED'
            ELSE 'UNKNOWN'
        END
        """
    )


def downgrade():
    op.drop_index("ix_job_postings_experience_type", table_name="job_postings")
    op.drop_column("job_postings", "experience_type")
