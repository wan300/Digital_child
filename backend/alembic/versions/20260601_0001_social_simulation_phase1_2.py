"""social simulation phase 1 and 2

Revision ID: 20260601_0001
Revises:
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260601_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "simulation_worlds" in existing_tables:
        return

    op.create_table(
        "simulation_worlds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("clock_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("speed", sa.Float(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("tick_no", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_simulation_worlds_name"), "simulation_worlds", ["name"], unique=False)
    op.create_index(op.f("ix_simulation_worlds_status"), "simulation_worlds", ["status"], unique=False)
    op.create_index(op.f("ix_simulation_worlds_tick_no"), "simulation_worlds", ["tick_no"], unique=False)

    op.create_table(
        "world_locations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["world_id"], ["simulation_worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_world_locations_kind"), "world_locations", ["kind"], unique=False)
    op.create_index(op.f("ix_world_locations_world_id"), "world_locations", ["world_id"], unique=False)
    op.create_index("ix_world_locations_world_name", "world_locations", ["world_id", "name"], unique=False)

    op.create_table(
        "community_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["world_id"], ["simulation_worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_community_rules_status"), "community_rules", ["status"], unique=False)
    op.create_index(op.f("ix_community_rules_world_id"), "community_rules", ["world_id"], unique=False)
    op.create_index("ix_community_rules_world_priority", "community_rules", ["world_id", "priority"], unique=False)

    op.create_table(
        "sim_agents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("persona_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("home_location_id", sa.String(length=36), nullable=True),
        sa.Column("current_location_id", sa.String(length=36), nullable=True),
        sa.Column("goals", sa.JSON(), nullable=False),
        sa.Column("traits", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["current_location_id"], ["world_locations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["home_location_id"], ["world_locations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["world_id"], ["simulation_worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sim_agents_current_location_id"), "sim_agents", ["current_location_id"], unique=False)
    op.create_index(op.f("ix_sim_agents_home_location_id"), "sim_agents", ["home_location_id"], unique=False)
    op.create_index(op.f("ix_sim_agents_name"), "sim_agents", ["name"], unique=False)
    op.create_index(op.f("ix_sim_agents_persona_id"), "sim_agents", ["persona_id"], unique=False)
    op.create_index(op.f("ix_sim_agents_status"), "sim_agents", ["status"], unique=False)
    op.create_index(op.f("ix_sim_agents_world_id"), "sim_agents", ["world_id"], unique=False)
    op.create_index("ix_sim_agents_world_persona", "sim_agents", ["world_id", "persona_id"], unique=False)

    op.create_table(
        "agent_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("needs", sa.JSON(), nullable=False),
        sa.Column("mood", sa.String(length=80), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("current_action", sa.Text(), nullable=False),
        sa.Column("cooldowns", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["sim_agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
    )
    op.create_index(op.f("ix_agent_states_agent_id"), "agent_states", ["agent_id"], unique=False)

    op.create_table(
        "simulation_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=True),
        sa.Column("action_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["sim_agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["world_id"], ["simulation_worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_simulation_actions_agent_id"), "simulation_actions", ["agent_id"], unique=False)
    op.create_index(op.f("ix_simulation_actions_status"), "simulation_actions", ["status"], unique=False)
    op.create_index(op.f("ix_simulation_actions_world_id"), "simulation_actions", ["world_id"], unique=False)

    op.create_table(
        "simulation_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("tick_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reference_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actors", sa.JSON(), nullable=False),
        sa.Column("location_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["world_locations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["world_id"], ["simulation_worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_simulation_events_event_type"), "simulation_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_simulation_events_location_id"), "simulation_events", ["location_id"], unique=False)
    op.create_index(op.f("ix_simulation_events_reference_time"), "simulation_events", ["reference_time"], unique=False)
    op.create_index(op.f("ix_simulation_events_status"), "simulation_events", ["status"], unique=False)
    op.create_index(op.f("ix_simulation_events_tick_no"), "simulation_events", ["tick_no"], unique=False)
    op.create_index(op.f("ix_simulation_events_world_id"), "simulation_events", ["world_id"], unique=False)
    op.create_index("ix_simulation_events_world_time", "simulation_events", ["world_id", "reference_time"], unique=False)

    op.create_table(
        "random_event_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("trigger", sa.JSON(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("cooldown", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("effect_prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_event_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["world_id"], ["simulation_worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_random_event_templates_last_triggered_event_id"), "random_event_templates", ["last_triggered_event_id"], unique=False)
    op.create_index(op.f("ix_random_event_templates_status"), "random_event_templates", ["status"], unique=False)
    op.create_index(op.f("ix_random_event_templates_world_id"), "random_event_templates", ["world_id"], unique=False)

    op.create_table(
        "user_interventions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("actor", sa.String(length=160), nullable=False),
        sa.Column("intervention_type", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("result_event_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["world_id"], ["simulation_worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_interventions_intervention_type"), "user_interventions", ["intervention_type"], unique=False)
    op.create_index(op.f("ix_user_interventions_result_event_id"), "user_interventions", ["result_event_id"], unique=False)
    op.create_index(op.f("ix_user_interventions_status"), "user_interventions", ["status"], unique=False)
    op.create_index(op.f("ix_user_interventions_world_id"), "user_interventions", ["world_id"], unique=False)

    op.create_table(
        "world_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("tick_no", sa.Integer(), nullable=False),
        sa.Column("clock_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("event_cursor", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["world_id"], ["simulation_worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_world_snapshots_event_cursor"), "world_snapshots", ["event_cursor"], unique=False)
    op.create_index(op.f("ix_world_snapshots_tick_no"), "world_snapshots", ["tick_no"], unique=False)
    op.create_index(op.f("ix_world_snapshots_world_id"), "world_snapshots", ["world_id"], unique=False)
    op.create_index("ix_world_snapshots_world_tick", "world_snapshots", ["world_id", "tick_no"], unique=False)


def downgrade() -> None:
    op.drop_table("world_snapshots")
    op.drop_table("user_interventions")
    op.drop_table("random_event_templates")
    op.drop_table("simulation_events")
    op.drop_table("simulation_actions")
    op.drop_table("agent_states")
    op.drop_table("sim_agents")
    op.drop_table("community_rules")
    op.drop_table("world_locations")
    op.drop_table("simulation_worlds")
