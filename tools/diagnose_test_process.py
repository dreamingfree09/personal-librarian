"""Observe unittest subprocess exits without converting failures into successes.

Only synthetic repository tests are run. Logs are written to ignored tmp/.
The canonical runs use the unmodified unittest command; observed/order runs
are supplementary and may themselves affect shutdown timing.
"""
from __future__ import annotations

import argparse
import atexit
import faulthandler
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading
import time


def observe(label: str) -> None:
    state = {"event": label, "pid": os.getpid(), "threads": [
        {"name": item.name, "daemon": item.daemon, "alive": item.is_alive()}
        for item in threading.enumerate()
    ]}
    qt = sys.modules.get("PySide6.QtCore")
    if qt is not None:
        # Observe an existing application only; do not create or drain one.
        app = qt.QCoreApplication.instance()
        state["qt_application_exists"] = app is not None
        if app is not None:
            state["qt_active_threads"] = qt.QThreadPool.globalInstance().activeThreadCount()
    print(json.dumps(state), file=sys.stderr, flush=True)


def child(mode: str) -> None:
    import unittest

    faulthandler.enable()
    # Match `python -m unittest`: fixture helpers also import `tests.*`.
    sys.path.insert(0, str(Path.cwd()))
    sys.path.insert(0, str(Path("tests").resolve()))
    atexit.register(observe, "python-atexit")
    observe("before-unittest")
    modules = sorted(path.stem for path in Path("tests").glob("test_*.py"))
    desktop = [name for name in modules if name.startswith("test_desktop")]
    other = [name for name in modules if name not in desktop]
    ordered = {
        "observed": modules,
        "desktop-first": desktop + other,
        "desktop-last": other + desktop,
        "non-desktop": other,
    }[mode]
    try:
        unittest.main(module=None, argv=["unittest", "-v", *ordered])
    except SystemExit as exc:
        print(json.dumps({"event": "unittest-system-exit", "code": exc.code}),
              file=sys.stderr, flush=True)
        observe("after-unittest")
        raise


def run_child(command: list[str], destination: Path, timeout: float = 900) -> dict:
    destination.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with (destination / "stdout.log").open("wb") as stdout, \
            (destination / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        start = {"pid": process.pid, "parent_pid": os.getpid(), "command": command}
        (destination / "started.json").write_text(json.dumps(start, indent=2), encoding="utf-8")
        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill only this disposable diagnostic child; timeout is always failure.
            timed_out = True
            process.kill()
            code = process.wait()
    output = (destination / "stderr.log").read_text(encoding="utf-8", errors="replace")
    result = {**start, "returncode": code, "returncode_hex": f"0x{code & 0xffffffff:08x}",
              "timed_out": timed_out, "seconds": time.monotonic() - started,
              "summary": re.findall(r"Ran \d+ tests? in .*|^OK.*$|^FAILED.*$", output, re.M)}
    (destination / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    print(output[-6000:], flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", choices=["observed", "desktop-first", "desktop-last", "non-desktop"])
    parser.add_argument("--output", type=Path, default=Path("tmp/ci-finalisation"))
    parser.add_argument("--groups", action="store_true")
    args = parser.parse_args()
    if args.child:
        child(args.child)
        raise AssertionError("unittest returned without SystemExit")
    args.output.mkdir(parents=True, exist_ok=False)
    inventory = {"pid": os.getpid(), "os": platform.platform(), "python": sys.version,
                 "executable": sys.executable, "cwd": str(Path.cwd()),
                 "dependencies": sorted(
                     (dist.metadata["Name"], dist.version) for dist in importlib.metadata.distributions())}
    (args.output / "environment.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(json.dumps(inventory), flush=True)
    base = [sys.executable, "-X", "faulthandler", "-u"]
    commands = [("full-1", [*base, "-m", "unittest", "discover", "-s", "tests", "-v"])]
    if args.groups:
        commands += [("full-2", commands[0][1])]
        for mode in ("observed", "desktop-first", "desktop-last", "non-desktop"):
            commands.append((mode, [*base, __file__, "--child", mode]))
        commands.append(("desktop-all", [*base, "-m", "unittest", "discover", "-s", "tests",
                                         "-p", "test_desktop*.py", "-v"]))
        for path in sorted(Path("tests").glob("test_desktop*.py")):
            commands.append((path.stem, [*base, "-m", "unittest", "discover", "-s", "tests",
                                         "-p", path.name, "-v"]))
    results = [run_child(command, args.output / label) for label, command in commands]
    (args.output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return int(any(item["returncode"] != 0 or item["timed_out"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
