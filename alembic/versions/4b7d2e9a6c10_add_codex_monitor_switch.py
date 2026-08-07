"""add default-off Codex Monitor switch

Revision ID: 4b7d2e9a6c10
Revises: 2f6c8a1d4e90
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4b7d2e9a6c10"
down_revision: Union[str, None] = "2f6c8a1d4e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("global_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "codex_monitor_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("global_settings", schema=None) as batch_op:
        batch_op.drop_column("codex_monitor_enabled")

