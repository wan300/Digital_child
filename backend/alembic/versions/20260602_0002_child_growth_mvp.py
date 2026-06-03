"""child growth mvp

Revision ID: 20260602_0002
Revises: 20260601_0001
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260602_0002"
down_revision: str | None = "20260601_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if not _has_table("child_world_drafts"):
        op.create_table(
            "child_world_drafts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("template_key", sa.String(length=80), nullable=False),
            sa.Column("input_params", sa.JSON(), nullable=False),
            sa.Column("natural_language_prompt", sa.Text(), nullable=False),
            sa.Column("raw_response", sa.Text(), nullable=False),
            sa.Column("parsed_draft", sa.JSON(), nullable=False),
            sa.Column("risk_flags", sa.JSON(), nullable=False),
            sa.Column("created_world_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_child_world_drafts_created_world_id"), "child_world_drafts", ["created_world_id"], unique=False)
        op.create_index(op.f("ix_child_world_drafts_status"), "child_world_drafts", ["status"], unique=False)
        op.create_index(op.f("ix_child_world_drafts_template_key"), "child_world_drafts", ["template_key"], unique=False)

    if not _has_table("agent_relationships"):
        op.create_table(
            "agent_relationships",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("world_id", sa.String(length=36), nullable=False),
            sa.Column("child_agent_id", sa.String(length=36), nullable=False),
            sa.Column("npc_agent_id", sa.String(length=36), nullable=False),
            sa.Column("relationship_type", sa.String(length=80), nullable=False),
            sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("evidence_buffer", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("last_summary", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["child_agent_id"], ["sim_agents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["npc_agent_id"], ["sim_agents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["world_id"], ["simulation_worlds.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_agent_relationships_child_agent_id"), "agent_relationships", ["child_agent_id"], unique=False)
        op.create_index(op.f("ix_agent_relationships_npc_agent_id"), "agent_relationships", ["npc_agent_id"], unique=False)
        op.create_index(op.f("ix_agent_relationships_relationship_type"), "agent_relationships", ["relationship_type"], unique=False)
        op.create_index(op.f("ix_agent_relationships_world_id"), "agent_relationships", ["world_id"], unique=False)
        op.create_index("ix_agent_relationships_world_pair", "agent_relationships", ["world_id", "child_agent_id", "npc_agent_id"], unique=False)

    if not _has_table("growth_reports"):
        op.create_table(
            "growth_reports",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("world_id", sa.String(length=36), nullable=False),
            sa.Column("child_agent_id", sa.String(length=36), nullable=False),
            sa.Column("period_start_tick", sa.Integer(), nullable=False),
            sa.Column("period_end_tick", sa.Integer(), nullable=False),
            sa.Column("report", sa.JSON(), nullable=False),
            sa.Column("source_event_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["child_agent_id"], ["sim_agents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["world_id"], ["simulation_worlds.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_growth_reports_child_agent_id"), "growth_reports", ["child_agent_id"], unique=False)
        op.create_index(op.f("ix_growth_reports_period_end_tick"), "growth_reports", ["period_end_tick"], unique=False)
        op.create_index(op.f("ix_growth_reports_period_start_tick"), "growth_reports", ["period_start_tick"], unique=False)
        op.create_index(op.f("ix_growth_reports_source_event_id"), "growth_reports", ["source_event_id"], unique=False)
        op.create_index(op.f("ix_growth_reports_world_id"), "growth_reports", ["world_id"], unique=False)
        op.create_index("ix_growth_reports_world_period", "growth_reports", ["world_id", "period_start_tick", "period_end_tick"], unique=False)


def downgrade() -> None:
    if _has_table("growth_reports"):
        op.drop_table("growth_reports")
    if _has_table("agent_relationships"):
        op.drop_table("agent_relationships")
    if _has_table("child_world_drafts"):
        op.drop_table("child_world_drafts")
