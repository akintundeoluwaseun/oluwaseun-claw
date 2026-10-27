"""Measure Claw, repeatably, with nothing installed that is not already here.

    backend/.venv/bin/python scripts/benchmark.py [--runs 5] [--json out.json]

What it measures, and why each one matters to someone using the app:

  cold start        how long from launching Claw to the backend answering. This is
                    the wait before anything can be typed.
  import cost       which modules that start-up is actually spent on, from
                    python -X importtime. This is where a slow launch gets fixed.
  tool latency      how long the ordinary tools take on real files.
  memory            resident memory after start-up and after work.
  idle              processor time used while nothing is happening, which on a
                    laptop is battery.

Every figure is the median of several runs, with the spread shown, on hardware
this script records. A single timing on an unnamed machine is not a measurement.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
PY = str(BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
sys.path.insert(0, str(BACKEND))

TOKEN = "b" * 40


# ---------- small helpers ----------
def rss_mb(pid: int | None = None) -> float:
    """Resident memory in MB, read from the system rather than guessed."""
    if sys.platform == "linux":
        path = f"/proc/{pid or 'self'}/status"
        for line in Path(path).read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 if sys.platform != "darwin" else 1024 * 1024)


def cpu_seconds(pid: int) -> float:
    if sys.platform != "linux":
        return float("nan")
    parts = Path(f"/proc/{pid}/stat").read_text().split()
    ticks = os.sysconf("SC_CLK_TCK")
    return (int(parts[13]) + int(parts[14])) / ticks


def summarise(samples: list[float]) -> dict:
    return {
        "runs": len(samples),
        "median": round(statistics.median(samples), 1),
        "min": round(min(samples), 1),
        "max": round(max(samples), 1),
        "spread": round(max(samples) - min(samples), 1),
    }


def free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------- 1. cold start ----------
def cold_start(runs: int) -> dict:
    """Launch the real backend and wait for /health, the way the app does."""
    samples, mem = [], []
    for _ in range(runs):
        data = Path(tempfile.mkdtemp(prefix="claw-bench-"))
        port = free_port()
        env = {**os.environ, "CLAW_SESSION_TOKEN": TOKEN, "CLAW_DATA_DIR": str(data)}
        started = time.perf_counter()
        proc = subprocess.Popen([PY, "-m", "claw.main", "--port", str(port)], cwd=BACKEND,
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = started + 60
            while time.perf_counter() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                        if r.status == 200:
                            break
                except Exception:  # noqa: BLE001 - not up yet
                    time.sleep(0.02)
            samples.append((time.perf_counter() - started) * 1000)
            time.sleep(0.4)
            mem.append(rss_mb(proc.pid))
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            shutil.rmtree(data, ignore_errors=True)
    return {"ms": summarise(samples), "rss_mb_after_start": round(statistics.median(mem), 1)}


# ---------- 2. where start-up goes ----------
def import_cost(top: int = 12) -> list[dict]:
    out = subprocess.run([PY, "-X", "importtime", "-c", "import claw.api.app"],
                         cwd=BACKEND, capture_output=True, text=True)
    rows = []
    for line in out.stderr.splitlines():
        m = re.match(r"import time:\s+(\d+)\s*\|\s*(\d+)\s*\|\s*(\S.*)$", line)
        if m:
            rows.append({"module": m.group(3).strip(), "cumulative_ms": int(m.group(2)) / 1000})
    # Only top-level packages: the cumulative figure already includes their children.
    best: dict[str, float] = {}
    for r in rows:
        head = r["module"].split(".")[0]
        best[head] = max(best.get(head, 0), r["cumulative_ms"])
    ranked = sorted(best.items(), key=lambda kv: -kv[1])[:top]
    return [{"package": k, "cumulative_ms": round(v, 1)} for k, v in ranked]


# ---------- 3. in-process timings ----------
def in_process(runs: int) -> dict:
    from claw.api.app import create_app
    from claw.tools.registry import build_registry
    from fastapi.testclient import TestClient

    before = rss_mb()
    reg_ms = []
    for _ in range(runs):
        t = time.perf_counter()
        build_registry()
        reg_ms.append((time.perf_counter() - t) * 1000)

    app_ms = []
    data = Path(tempfile.mkdtemp(prefix="claw-bench-app-"))
    for _ in range(runs):
        t = time.perf_counter()
        create_app(data, TOKEN)
        app_ms.append((time.perf_counter() - t) * 1000)

    client = TestClient(create_app(data, TOKEN), base_url="http://127.0.0.1")
    client.headers["X-Claw-Token"] = TOKEN
    routes = {}
    for name, call in (("GET /health", lambda: client.get("/health")),
                       ("GET /settings", lambda: client.get("/settings")),
                       ("GET /edition", lambda: client.get("/edition")),
                       ("GET /tasks", lambda: client.get("/tasks")),
                       ("GET /models/status", lambda: client.get("/models/status"))):
        samples = []
        for _ in range(runs):
            t = time.perf_counter()
            call()
            samples.append((time.perf_counter() - t) * 1000)
        routes[name] = summarise(samples)
    shutil.rmtree(data, ignore_errors=True)
    return {"build_registry_ms": summarise(reg_ms), "create_app_ms": summarise(app_ms),
            "routes": routes, "rss_mb_before": round(before, 1), "rss_mb_after": round(rss_mb(), 1)}


# ---------- 4. the tools, on real files ----------
def tools(runs: int) -> dict:
    from claw.browser.session import BrowserSession
    from claw.config import Settings
    from claw.permissions.policy import PermissionPolicy
    from claw.tools.base import ToolContext
    from claw.tools.registry import build_registry

    reg = build_registry()
    root = Path(tempfile.mkdtemp(prefix="claw-bench-tools-"))
    docs, data = root / "Documents", root / "data"
    docs.mkdir(parents=True)
    data.mkdir()

    # A 1 MB text file and 300 small ones: ordinary sizes, not toy ones.
    big = docs / "big.txt"
    big.write_text("S-CLAW is a desktop agent.\n" * 30_000, encoding="utf-8")
    for i in range(300):
        (docs / f"note-{i:03}.txt").write_text(f"note {i}\n", encoding="utf-8")
    other = docs / "big-2.txt"
    other.write_text(big.read_text(encoding="utf-8").replace("agent", "assistant", 50), encoding="utf-8")

    s = Settings()
    s.permissions.authorized_folders = [str(docs)]
    browser = BrowserSession(data, lambda: s.browser)
    ctx = ToolContext(settings=s, policy=PermissionPolicy(s.permissions.modes, s.permissions.authorized_folders),
                      data_dir=data, browser=browser, task_id="bench")

    cases = [
        ("read_file (1 MB)", "read_file", {"path": str(big)}),
        ("count_text (1 MB)", "count_text", {"path": str(big)}),
        ("search_in_file (1 MB)", "search_in_file", {"path": str(big), "query": "desktop"}),
        ("compare_files (1 MB x2)", "compare_files", {"first": str(big), "second": str(other)}),
        ("find_files (300 files)", "find_files", {"folder": str(docs), "extension": ".txt"}),
        ("list_folder (300 files)", "list_folder", {"folder": str(docs)}),
        ("current_time", "current_time", {}),
        ("disk_space", "disk_space", {"path": str(docs)}),
        ("is_program_running", "is_program_running", {"program": "python"}),
    ]

    async def run() -> dict:
        out = {}
        for label, name, args in cases:
            spec = reg.get(name)
            samples = []
            for i in range(runs):
                parsed = spec.parse_args(args)
                t = time.perf_counter()
                await spec.handler(parsed, ctx)
                samples.append((time.perf_counter() - t) * 1000)
            out[label] = summarise(samples)
        await browser.close()
        return out

    result = asyncio.run(run())
    shutil.rmtree(root, ignore_errors=True)
    return result


# ---------- 5. idle ----------
def idle(seconds: int = 10) -> dict:
    """Processor time used while the backend sits there doing nothing."""
    data = Path(tempfile.mkdtemp(prefix="claw-bench-idle-"))
    port = free_port()
    env = {**os.environ, "CLAW_SESSION_TOKEN": TOKEN, "CLAW_DATA_DIR": str(data)}
    proc = subprocess.Popen([PY, "-m", "claw.main", "--port", str(port)], cwd=BACKEND,
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.perf_counter() + 60
        while time.perf_counter() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:  # noqa: BLE001
                time.sleep(0.02)
        time.sleep(1.0)
        start_cpu, start_rss = cpu_seconds(proc.pid), rss_mb(proc.pid)
        time.sleep(seconds)
        used = cpu_seconds(proc.pid) - start_cpu
        return {"window_s": seconds, "cpu_seconds": round(used, 3),
                "cpu_percent_of_one_core": round(100 * used / seconds, 2),
                "rss_mb_start": round(start_rss, 1), "rss_mb_end": round(rss_mb(proc.pid), 1)}
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)


def hardware() -> dict:
    cpu = platform.processor() or platform.machine()
    if sys.platform == "linux":
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
        mem = next((int(l.split()[1]) / 1024 / 1024 for l in Path("/proc/meminfo").read_text().splitlines()
                    if l.startswith("MemTotal")), 0)
    else:
        mem = 0
    return {"platform": platform.platform(), "python": platform.python_version(),
            "cpu": cpu, "cores": os.cpu_count(), "memory_gb": round(mem, 1),
            "when": time.strftime("%Y-%m-%d %H:%M:%S %Z")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--idle-seconds", type=int, default=10)
    ap.add_argument("--json", default="")
    ap.add_argument("--skip", default="", help="comma-separated: cold,imports,process,tools,idle")
    args = ap.parse_args()
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    report: dict = {"hardware": hardware(), "runs": args.runs}
    hw = report["hardware"]
    print(f"{hw['cpu']}, {hw['cores']} cores, {hw['memory_gb']} GB, {hw['python']}, {hw['platform']}")
    print(f"{args.runs} runs per measurement\n")

    if "cold" not in skip:
        report["cold_start"] = cold_start(args.runs)
        c = report["cold_start"]
        print(f"Cold start (launch -> /health answers)   {c['ms']['median']:>8.0f} ms   "
              f"[{c['ms']['min']:.0f}-{c['ms']['max']:.0f}]   {c['rss_mb_after_start']} MB resident")
    if "imports" not in skip:
        report["import_cost"] = import_cost()
        print("\nWhere start-up goes (cumulative import time):")
        for row in report["import_cost"]:
            print(f"   {row['package']:<28} {row['cumulative_ms']:>8.1f} ms")
    if "process" not in skip:
        report["in_process"] = in_process(args.runs)
        p = report["in_process"]
        print(f"\nbuild_registry()                         {p['build_registry_ms']['median']:>8.1f} ms")
        print(f"create_app()                             {p['create_app_ms']['median']:>8.1f} ms")
        for name, st in p["routes"].items():
            print(f"   {name:<38} {st['median']:>8.1f} ms")
    if "tools" not in skip:
        report["tools"] = tools(args.runs)
        print("\nTools, on real files:")
        for label, st in report["tools"].items():
            print(f"   {label:<28} {st['median']:>8.1f} ms   [{st['min']:.1f}-{st['max']:.1f}]")
    if "idle" not in skip:
        report["idle"] = idle(args.idle_seconds)
        i = report["idle"]
        print(f"\nIdle over {i['window_s']}s: {i['cpu_seconds']}s of processor time "
              f"({i['cpu_percent_of_one_core']}% of one core), {i['rss_mb_end']} MB resident")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
