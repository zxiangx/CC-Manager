from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class MessageBranch(Base):
    """One user-message position with multiple immutable Task contexts."""

    __tablename__ = "message_branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MessageBranchVersion(Base):
    """One Task/thread participating in a message branch group."""

    __tablename__ = "message_branch_versions"
    __table_args__ = (
        UniqueConstraint(
            "branch_id",
            "task_id",
            name="uq_message_branch_versions_branch_task",
        ),
        UniqueConstraint(
            "branch_id",
            "ordinal",
            name="uq_message_branch_versions_branch_ordinal",
        ),
        UniqueConstraint(
            "task_id",
            "message_log_id",
            name="uq_message_branch_versions_task_message",
        ),
        Index(
            "ix_message_branch_versions_task_message",
            "task_id",
            "message_log_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("message_branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL is either the original Task description or a newly-forked draft
    # waiting for its first edited message to be sent.
    message_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("log_entries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_initial: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
