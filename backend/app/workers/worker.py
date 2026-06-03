from __future__ import annotations

import asyncio
import contextlib
import signal

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.simulation.scheduler import SimulationScheduler


async def main() -> None:
    settings = get_settings()
    scheduler = SimulationScheduler()
    stop = asyncio.Event()

    def _stop() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(getattr(signal, signame), _stop)
    print("memory_orchestrator worker started; simulation polling mode is active")
    while not stop.is_set():
        try:
            async with AsyncSessionLocal() as session:
                await scheduler.step_running_worlds(session)
        except Exception as exc:
            print(f"simulation worker tick failed: {type(exc).__name__}: {exc}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.simulation_worker_interval_seconds)
        except TimeoutError:
            continue


if __name__ == "__main__":
    asyncio.run(main())
