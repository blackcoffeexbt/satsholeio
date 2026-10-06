import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from loguru import logger

VERSION = "city-7"
MAP_VERSION = "bitcoin-borough-7"
_replay_slots = asyncio.Semaphore(2)


async def verify(run, inputs):
    node = shutil.which("node")
    context = logger.bind(run_id=run.get("id", "operator-replay"))
    script = str(Path(__file__).with_name("verify.cjs").resolve())
    context.info(
        "SatsHole verifier start: run={} node={} script={} cwd={}",
        run.get("id", "operator-replay"),
        node,
        script,
        os.getcwd(),
    )
    if not node:
        context.error("SatsHole verifier unavailable: Node executable not found")
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
        context.warning("SatsHole verifier rejected oversized payload")
        raise ValueError("Replay payload too large")
    if _replay_slots.locked():
        context.warning("SatsHole verifier capacity busy")
        raise RuntimeError("Replay capacity busy; retry later")
    async with _replay_slots:
        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                node,
                "--max-old-space-size=128",
                script,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            context.error("SatsHole verifier launch failed: {}", type(exc).__name__)
            raise
        try:
            out, stderr = await asyncio.wait_for(
                process.communicate(payload.encode()), 30
            )
        except BaseException as exc:
            context.error(
                "SatsHole verifier interrupted: reason={} elapsed={:.2f}s",
                type(exc).__name__,
                time.monotonic() - started,
            )
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        context.info(
            "SatsHole verifier finished: run={} exit={} elapsed={:.2f}s stderr={}",
            run.get("id", "operator-replay"),
            process.returncode,
            time.monotonic() - started,
            stderr.decode("utf-8", errors="replace")[:4096],
        )
        if process.returncode:
            raise ValueError("Input replay rejected")
        try:
            return json.loads(out)
        except ValueError:
            context.error(
                "SatsHole verifier returned invalid JSON ({} bytes)", len(out)
            )
            raise
