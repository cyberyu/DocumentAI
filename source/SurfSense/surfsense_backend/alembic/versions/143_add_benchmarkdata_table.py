"""143_add_benchmarkdata_table

Revision ID: 143
Revises: 142
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "143"
down_revision: str | None = "142"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmarkdata_table",
        sa.Column("benchmarkdata_id", sa.Integer(), nullable=False),
        sa.Column("doc_id", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=128), nullable=False),
        sa.Column("task_num", sa.Integer(), nullable=False),
        sa.Column("created_date", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("dataset_filename", sa.String(length=512), nullable=False),
        sa.Column("dataset_content", sa.Text(), nullable=False),
        sa.Column("dataset_mime_type", sa.String(length=255), nullable=True),
        sa.Column("dataset_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["doc_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("benchmarkdata_id"),
    )
    op.create_index(
        op.f("ix_benchmarkdata_table_benchmarkdata_id"),
        "benchmarkdata_table",
        ["benchmarkdata_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_benchmarkdata_table_created_date"),
        "benchmarkdata_table",
        ["created_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_benchmarkdata_table_doc_id"),
        "benchmarkdata_table",
        ["doc_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_benchmarkdata_table_task_type"),
        "benchmarkdata_table",
        ["task_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_benchmarkdata_table_task_type"), table_name="benchmarkdata_table")
    op.drop_index(op.f("ix_benchmarkdata_table_doc_id"), table_name="benchmarkdata_table")
    op.drop_index(op.f("ix_benchmarkdata_table_created_date"), table_name="benchmarkdata_table")
    op.drop_index(op.f("ix_benchmarkdata_table_benchmarkdata_id"), table_name="benchmarkdata_table")
    op.drop_table("benchmarkdata_table")
