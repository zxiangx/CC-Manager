"""add immutable user-message branch versions

Revision ID: 6d9e2f4a1b70
Revises: 4b7d2e9a6c10
Create Date: 2026-08-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6d9e2f4a1b70"
down_revision: Union[str, None] = "4b7d2e9a6c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "message_branches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_message_branches_created_by",
        "message_branches",
        ["created_by"],
        unique=False,
    )
    op.create_table(
        "message_branch_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("message_log_id", sa.Integer(), nullable=True),
        sa.Column(
            "is_initial",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["message_branches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["message_log_id"], ["log_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "branch_id",
            "ordinal",
            name="uq_message_branch_versions_branch_ordinal",
        ),
        sa.UniqueConstraint(
            "branch_id",
            "task_id",
            name="uq_message_branch_versions_branch_task",
        ),
        sa.UniqueConstraint(
            "task_id",
            "message_log_id",
            name="uq_message_branch_versions_task_message",
        ),
    )
    op.create_index(
        "ix_message_branch_versions_branch_id",
        "message_branch_versions",
        ["branch_id"],
        unique=False,
    )
    op.create_index(
        "ix_message_branch_versions_message_log_id",
        "message_branch_versions",
        ["message_log_id"],
        unique=False,
    )
    op.create_index(
        "ix_message_branch_versions_task_id",
        "message_branch_versions",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        "ix_message_branch_versions_task_message",
        "message_branch_versions",
        ["task_id", "message_log_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("message_branch_versions")
    op.drop_table("message_branches")
