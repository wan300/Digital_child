import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.init_db import _ensure_schema_compatibility


@pytest.mark.asyncio
async def test_schema_compatibility_adds_child_observation_description_columns(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE child_multimodal_observation_drafts (
                    id VARCHAR(36) PRIMARY KEY,
                    observable_summary TEXT NOT NULL
                )
                """
            )
        )
        await conn.run_sync(_ensure_schema_compatibility)

        columns = await conn.run_sync(
            lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("child_multimodal_observation_drafts")}
        )

    assert "generated_child_description" in columns
    assert "accepted_child_description" in columns
    await engine.dispose()
