"""child multimodal observation drafts

Revision ID: 20260618_0003
Revises: 20260602_0002
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260618_0003"
down_revision: str | None = "20260602_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return name in set(sa.inspect(op.get_bind()).get_table_names())


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if not _has_table("media_assets"):
        op.create_table(
            "media_assets",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_actor", sa.String(length=160), nullable=False),
            sa.Column("original_filename", sa.String(length=260), nullable=False),
            sa.Column("media_type", sa.String(length=24), nullable=False),
            sa.Column("mime_type", sa.String(length=120), nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("storage_path", sa.Text(), nullable=True),
            sa.Column("preview_refs", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("privacy_flags", sa.JSON(), nullable=False),
            sa.Column("deletion_reason", sa.String(length=80), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_media_assets_media_type"), "media_assets", ["media_type"], unique=False)
        op.create_index(op.f("ix_media_assets_owner_actor"), "media_assets", ["owner_actor"], unique=False)
        op.create_index(op.f("ix_media_assets_sha256"), "media_assets", ["sha256"], unique=False)
        op.create_index(op.f("ix_media_assets_status"), "media_assets", ["status"], unique=False)

    if not _has_table("media_analysis_jobs"):
        op.create_table(
            "media_analysis_jobs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("asset_ids", sa.JSON(), nullable=False),
            sa.Column("analyzed_asset_ids", sa.JSON(), nullable=False),
            sa.Column("pending_asset_ids", sa.JSON(), nullable=False),
            sa.Column("skipped_asset_ids", sa.JSON(), nullable=False),
            sa.Column("excluded_asset_ids", sa.JSON(), nullable=False),
            sa.Column("target_child", sa.JSON(), nullable=False),
            sa.Column("model_provider", sa.String(length=80), nullable=False),
            sa.Column("model_name", sa.String(length=160), nullable=False),
            sa.Column("prompt_version", sa.String(length=120), nullable=False),
            sa.Column("raw_response", sa.Text(), nullable=False),
            sa.Column("normalized_result", sa.JSON(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_media_analysis_jobs_status"), "media_analysis_jobs", ["status"], unique=False)

    if not _has_table("child_multimodal_observation_drafts"):
        op.create_table(
            "child_multimodal_observation_drafts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("analysis_job_id", sa.String(length=36), nullable=False),
            sa.Column("child_world_draft_id", sa.String(length=36), nullable=True),
            sa.Column("structured_setup", sa.JSON(), nullable=False),
            sa.Column("target_child", sa.JSON(), nullable=False),
            sa.Column("observable_summary", sa.Text(), nullable=False),
            sa.Column("generated_child_description", sa.Text(), nullable=False),
            sa.Column("accepted_child_description", sa.Text(), nullable=False),
            sa.Column("visible_observations", sa.JSON(), nullable=False),
            sa.Column("audio_observations", sa.JSON(), nullable=False),
            sa.Column("non_identifying_appearance", sa.JSON(), nullable=False),
            sa.Column("behavior_signals", sa.JSON(), nullable=False),
            sa.Column("temperament_hypotheses", sa.JSON(), nullable=False),
            sa.Column("interests", sa.JSON(), nullable=False),
            sa.Column("development_hints", sa.JSON(), nullable=False),
            sa.Column("avatar_brief", sa.JSON(), nullable=False),
            sa.Column("initial_memory_candidates", sa.JSON(), nullable=False),
            sa.Column("unknowns", sa.JSON(), nullable=False),
            sa.Column("risk_flags", sa.JSON(), nullable=False),
            sa.Column("authorization_confirmation", sa.JSON(), nullable=False),
            sa.Column("approved_payload", sa.JSON(), nullable=False),
            sa.Column("rejected_reason", sa.Text(), nullable=False),
            sa.Column("raw_media_deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["analysis_job_id"], ["media_analysis_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["child_world_draft_id"], ["child_world_drafts.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_child_multimodal_observation_drafts_analysis_job_id"),
            "child_multimodal_observation_drafts",
            ["analysis_job_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_child_multimodal_observation_drafts_child_world_draft_id"),
            "child_multimodal_observation_drafts",
            ["child_world_draft_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_child_multimodal_observation_drafts_status"),
            "child_multimodal_observation_drafts",
            ["status"],
            unique=False,
        )

    if _has_table("child_multimodal_observation_drafts") and not _has_column("child_multimodal_observation_drafts", "generated_child_description"):
        op.add_column(
            "child_multimodal_observation_drafts",
            sa.Column("generated_child_description", sa.Text(), nullable=False, server_default=""),
        )

    if _has_table("child_multimodal_observation_drafts") and not _has_column("child_multimodal_observation_drafts", "accepted_child_description"):
        op.add_column(
            "child_multimodal_observation_drafts",
            sa.Column("accepted_child_description", sa.Text(), nullable=False, server_default=""),
        )

    if not _has_table("observation_review_decisions"):
        op.create_table(
            "observation_review_decisions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("observation_draft_id", sa.String(length=36), nullable=False),
            sa.Column("item_path", sa.String(length=240), nullable=False),
            sa.Column("decision", sa.String(length=40), nullable=False),
            sa.Column("original_value", sa.JSON(), nullable=False),
            sa.Column("final_value", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("evidence_refs", sa.JSON(), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["observation_draft_id"], ["child_multimodal_observation_drafts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_observation_review_decisions_decision"),
            "observation_review_decisions",
            ["decision"],
            unique=False,
        )
        op.create_index(
            op.f("ix_observation_review_decisions_observation_draft_id"),
            "observation_review_decisions",
            ["observation_draft_id"],
            unique=False,
        )


def downgrade() -> None:
    if _has_table("observation_review_decisions"):
        op.drop_table("observation_review_decisions")
    if _has_table("child_multimodal_observation_drafts"):
        op.drop_table("child_multimodal_observation_drafts")
    if _has_table("media_analysis_jobs"):
        op.drop_table("media_analysis_jobs")
    if _has_table("media_assets"):
        op.drop_table("media_assets")
