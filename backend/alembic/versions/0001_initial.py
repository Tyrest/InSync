"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("jellyfin_user_id", sa.String(length=128), nullable=False),
        sa.Column("jellyfin_username", sa.String(length=256), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_jellyfin_user_id", "users", ["jellyfin_user_id"], unique=True)

    op.create_table(
        "tracks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("artist", sa.String(length=512), nullable=False),
        sa.Column("album", sa.String(length=512), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("source_platform", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tracks_source_id", "tracks", ["source_id"], unique=True)
    op.create_table(
        "oauth_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=256), nullable=False),
        sa.Column("code_verifier", sa.String(length=256), nullable=True),
        sa.Column("redirect_uri", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_oauth_states_state", "oauth_states", ["state"], unique=True)

    op.create_table(
        "platform_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("credentials_json", sa.Text(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "synced_playlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("platform_playlist_id", sa.String(length=256), nullable=False),
        sa.Column("platform_playlist_name", sa.String(length=512), nullable=False),
        sa.Column("jellyfin_playlist_id", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_synced", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "download_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("search_query", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("artist", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "synced_playlist_tracks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "synced_playlist_id",
            sa.Integer(),
            sa.ForeignKey("synced_playlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_config")
    op.drop_table("synced_playlist_tracks")
    op.drop_table("download_tasks")
    op.drop_table("synced_playlists")
    op.drop_index("ix_oauth_states_state", table_name="oauth_states")
    op.drop_table("oauth_states")
    op.drop_table("platform_links")
    op.drop_table("tracks")
    op.drop_index("ix_users_jellyfin_user_id", table_name="users")
    op.drop_table("users")
