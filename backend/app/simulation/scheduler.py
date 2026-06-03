from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from redis import asyncio as redis_async
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import SimulationWorld
from app.simulation.engine import SimulationEngine


class SimulationScheduler:
    _local_locks: set[str] = set()

    def __init__(self) -> None:
        self.settings = get_settings()
        self.engine = SimulationEngine()
        self._redis = None
        self._redis_attempted = False

    async def step_running_worlds(self, session: AsyncSession) -> int:
        worlds = (
            await session.execute(select(SimulationWorld).where(SimulationWorld.status == "running").order_by(SimulationWorld.updated_at))
        ).scalars().all()
        stepped = 0
        for world in worlds:
            async with self.world_lock(world.id) as acquired:
                if not acquired:
                    continue
                await self.engine.step(session, world.id)
                await session.commit()
                stepped += 1
        return stepped

    @contextlib.asynccontextmanager
    async def world_lock(self, world_id: str, *, blocking_timeout: float = 0.0) -> AsyncIterator[bool]:
        redis = await self._get_redis()
        if redis is not None:
            lock_timeout = max(30, int(self.settings.simulation_step_lock_timeout_seconds))
            lock = redis.lock(f"simulation:world:{world_id}:step", timeout=lock_timeout, blocking_timeout=0)
            acquired = False
            try:
                acquired = await lock.acquire(blocking=blocking_timeout > 0, blocking_timeout=blocking_timeout)
                yield acquired
            finally:
                if acquired:
                    with contextlib.suppress(Exception):
                        await lock.release()
            return

        if world_id in self._local_locks:
            if blocking_timeout > 0:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + blocking_timeout
                while world_id in self._local_locks and loop.time() < deadline:
                    await asyncio.sleep(0.05)
                if world_id not in self._local_locks:
                    self._local_locks.add(world_id)
                    try:
                        yield True
                    finally:
                        self._local_locks.discard(world_id)
                    return
            yield False
            return
        self._local_locks.add(world_id)
        try:
            yield True
        finally:
            self._local_locks.discard(world_id)

    async def _get_redis(self):
        if self._redis_attempted:
            return self._redis
        self._redis_attempted = True
        try:
            client = redis_async.from_url(self.settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
            await client.ping()
            self._redis = client
        except Exception:
            self._redis = None
        return self._redis
