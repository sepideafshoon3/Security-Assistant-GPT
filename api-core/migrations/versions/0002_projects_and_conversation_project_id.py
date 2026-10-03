"""Projects (folders) and conversations.project_id.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07

Replaces the ``_patch_conversations_project_id`` stopgap that used to run on
every app startup. Like 0001, each step is skipped if a pre-Alembic dev
database already has it (the stopgap may have added the column and index).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Offline (`--sql`) mode has no database to inspect: emit everything.
    offline = context.is_offline_mode()
    inspector = None if offline else sa.inspect(op.get_bind())

    if offline or not inspector.has_table("projects"):
        op.create_table(
            "projects",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_projects_user_id_updated_at", "projects", ["user_id", "updated_at"]
        )

    columns = (
        set()
        if offline
        else {c["name"] for c in inspector.get_columns("conversations")}
    )
    if "project_id" not in columns:
        with op.batch_alter_table("conversations") as batch:
            batch.add_column(
                sa.Column(
                    "project_id",
                    sa.String(length=36),
                    sa.ForeignKey(
                        "projects.id",
                        name="fk_conversations_project_id_projects",
                        ondelete="SET NULL",
                    ),
                    nullable=True,
                )
            )

    indexes = (
        set()
        if offline
        else {i["name"] for i in inspector.get_indexes("conversations")}
    )
    if "ix_conversations_project_id" not in indexes:
        op.create_index("ix_conversations_project_id", "conversations", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_project_id", table_name="conversations")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("project_id")
    op.drop_table("projects")
