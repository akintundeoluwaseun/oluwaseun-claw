"""Download one catalogue brain with Claw's own downloader (licence check, disk check, resume, SHA-256),
into <data_dir>/models/<id>/ with its manifest — the same files a user gets from Settings.

    python packaging/fetch_brain.py qwen3-vl-4b --data-dir build/brain-data

Used by the Windows build workflow to bundle a brain into the installer.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claw.runtime import catalog  # noqa: E402
from claw.runtime.brain import Brain  # noqa: E402
from claw.runtime.store import ModelStore  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_id", choices=[e.id for e in catalog.CATALOG])
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    entry = next(e for e in catalog.CATALOG if e.id == args.model_id)
    brain = Brain(ModelStore(Path(args.data_dir)))
    task = asyncio.create_task(brain._download(entry))
    last = 0.0
    while not task.done():
        await asyncio.sleep(5)
        d = brain.download.as_dict()
        if time.monotonic() - last > 30:
            print(f"{d['status']}: {d['done_bytes'] / 1024**3:.2f} / {d['total_bytes'] / 1024**3:.2f} GB  {d['message']}", flush=True)
            last = time.monotonic()
    await task
    d = brain.download.as_dict()
    print(f"final: {d['status']} — {d['message']}")
    installed = brain.store.get(entry.id)
    if d["status"] != "done" or installed is None:
        return 1
    print(f"saved to {brain.store.folder_for(entry.id)} (licence {installed.license}, checksum verified: {installed.verified})")
    return 0 if installed.verified else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
