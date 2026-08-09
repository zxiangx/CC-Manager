"""persist the active internal message branch task

Revision ID: 8c1f4a7d2e90
Revises: 6d9e2f4a1b70
Create Date: 2026-08-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c1f4a7d2e90"
down_revision: Union[str, None] = "6d9e2f4a1b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column(
            "message_branch_root_task_id", sa.Integer(), nullable=True
        ))
        batch_op.add_column(sa.Column(
            "active_message_branch_task_id", sa.Integer(), nullable=True
        ))
        batch_op.create_foreign_key(
            "fk_tasks_message_branch_root_task_id_tasks",
            "tasks",
            ["message_branch_root_task_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_tasks_active_message_branch_task_id_tasks",
            "tasks",
            ["active_message_branch_task_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_tasks_message_branch_root_task_id",
            ["message_branch_root_task_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_tasks_active_message_branch_task_id",
            ["active_message_branch_task_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index("ix_tasks_active_message_branch_task_id")
        batch_op.drop_index("ix_tasks_message_branch_root_task_id")
        batch_op.drop_constraint(
            "fk_tasks_active_message_branch_task_id_tasks",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_tasks_message_branch_root_task_id_tasks",
            type_="foreignkey",
        )
        batch_op.drop_column("active_message_branch_task_id")
        batch_op.drop_column("message_branch_root_task_id")
