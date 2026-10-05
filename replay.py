import asyncio
import json
import shutil
from pathlib import Path

VERSION = "city-4"
MAP_VERSION = "bitcoin-borough-4"
_replay_slots = asyncio.Semaphore(2)


async def verify(run, inputs):
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Server replay requires Node.js 18 or later")
    payload = json.dumps(
        {
            "version": run["game_version"],
            "map": run["map_version"],
            "seed": run["seed"],
            "config": run["config"],
            "inputs": inputs,
        }
    )
    if len(payload.encode()) > 256_000:
        raise ValueError("Replay payload too large")
    if _replay_slots.locked():
        raise RuntimeError("Replay capacity busy; retry later")
    async with _replay_slots:
        process = await asyncio.create_subprocess_exec(
            node,
            "--max-old-space-size=128",
            str(Path(__file__).with_name("verify.cjs")),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, _ = await asyncio.wait_for(process.communicate(payload.encode()), 30)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise ValueError("Input replay rejected")
        return json.loads(out)
