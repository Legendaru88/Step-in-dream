"""initial schema

Revision ID: 20260222_0001
Revises:
Create Date: 2026-02-22 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260222_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    goal_status = sa.Enum("active", "completed", "paused", name="goal_status")
    step_status = sa.Enum("pending", "done", "skipped", name="step_status")
    dialog_role = sa.Enum("user", "assistant", name="dialog_role")

    goal_status.create(op.get_bind(), checkfirst=True)
    step_status.create(op.get_bind(), checkfirst=True)
    dialog_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)

    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", goal_status, nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_goals_user_id"), "goals", ["user_id"], unique=False)

    op.create_table(
        "dialog_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=True),
        sa.Column("role", dialog_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dialog_logs_user_id"), "dialog_logs", ["user_id"], unique=False)

    op.create_table(
        "steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("status", step_status, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_steps_goal_id"), "steps", ["goal_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_steps_goal_id"), table_name="steps")
    op.drop_table("steps")

    op.drop_index(op.f("ix_dialog_logs_user_id"), table_name="dialog_logs")
    op.drop_table("dialog_logs")

    op.drop_index(op.f("ix_goals_user_id"), table_name="goals")
    op.drop_table("goals")

    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")

    sa.Enum("user", "assistant", name="dialog_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum("pending", "done", "skipped", name="step_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum("active", "completed", "paused", name="goal_status").drop(op.get_bind(), checkfirst=True)
