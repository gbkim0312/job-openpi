"""initial schema

Revision ID: 0001_initial
Revises:
"""

from alembic import op

from job_collector.persistence import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(
        op.get_bind(),
        tables=[
            Base.metadata.tables["job_postings"],
            Base.metadata.tables["job_snapshots"],
            Base.metadata.tables["crawl_runs"],
        ],
    )


def downgrade():
    Base.metadata.drop_all(op.get_bind())
