#!/usr/bin/env python3
from __future__ import annotations
"""
Internal reconnect worker for SSH tunnels.

Launched as a detached subprocess by SSHTunnel. Reads a JSON spec file
(path passed as argv[1]) and runs the gh codespace ssh reconnect loop.
Exits gracefully on SIGTERM/SIGINT or when the stop file is touched.

Debug mode:
    python -m csproxy._worker /path/to/spec.json --debug
"""

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("spec_path", help="Path to JSON worker spec file")
    parser.add_argument("--debug", action="store_true", help="Print debug output to stderr")
    args = parser.parse_args()

    spec_path = Path(args.spec_path)
    debug = args.debug

    if not spec_path.exists():
        print(f"Worker spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    try:
        spec = json.loads(spec_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"Failed to read worker spec: {e}", file=sys.stderr)
        sys.exit(1)

    log_file = Path(spec["log_file"])
    stop_file = Path(spec["stop_file"])
    reconnect_delay = spec.get("reconnect_delay", 5)
    max_reconnect_delay = spec.get("max_reconnect_delay", 300)
    gh_cmd = spec["gh_cmd"]

    stop_requested = False

    def _on_signal(signum: int, frame) -> None:
        nonlocal stop_requested
        if debug:
            print(f"[worker] Received signal {signum}, setting stop flag", file=sys.stderr)
        stop_requested = True

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    delay = reconnect_delay
    attempt = 0
    while not stop_requested:
        if stop_file.exists():
            if debug:
                print("[worker] Stop file detected, exiting", file=sys.stderr)
            stop_file.unlink(missing_ok=True)
            break

        attempt += 1
        if debug:
            print(f"[worker] Attempt {attempt}: running gh ssh (delay={delay}s)", file=sys.stderr)

        log_mode = "a" if log_file.exists() else "w"
        try:
            with open(log_file, log_mode) as log_fd:
                subprocess.run(gh_cmd, stdout=log_fd, stderr=log_fd, timeout=60)
        except subprocess.TimeoutExpired:
            if debug:
                print("[worker] SSH command timed out, reconnecting...", file=sys.stderr)
        except OSError as e:
            # Log file may have become unavailable (e.g. config dir deleted)
            print(f"[worker] Log file error: {e}", file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, max_reconnect_delay)
            continue

        if stop_file.exists():
            stop_file.unlink(missing_ok=True)
            break

        if stop_requested:
            break

        # Add jitter (±25%) to prevent thunder-herding when multiple tunnels
        # reconnect simultaneously after a GitHub SSH endpoint blip.
        jittered = delay * (1 + random.uniform(-0.25, 0.25))
        time.sleep(max(0.5, jittered))
        delay = min(delay * 2, max_reconnect_delay)

    if debug:
        print("[worker] Exiting cleanly", file=sys.stderr)

    # Clean up spec file to indicate worker exited
    spec_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
