#!/usr/bin/env python3
from __future__ import annotations
"""
Lightweight JSON-based state management for csproxy.

Replaces fragile flat PID files with a single atomic state.json.
All writes are atomic (tempfile + os.replace) and guarded by a
spinlock (os.O_CREAT|os.O_EXCL) with stale-lock detection.

Locking notes:
- os.O_CREAT | os.O_EXCL is atomic on POSIX and on Windows NTFS.
- On Windows network drives (SMB) the atomicity guarantee may be weaker,
  so we combine it with mtime-based stale-lock detection as a fallback.
- The lock file contains the PID of the holder. If that process is dead
  (or the lock file is older than 30s), we force-break it.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional


def _pid_exists(pid: int) -> bool:
    """Check whether a process with the given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


class State:
    """Thread-safe(ish) JSON state store for tunnel metadata."""

    def __init__(self, config_dir: Path) -> None:
        self.path = config_dir / "state.json"
        self._lock_path = config_dir / "state.lock"
        self._ensure_dir()
        self._migrate_from_pid_files(config_dir)

    def _ensure_dir(self) -> None:
        """Create parent directories if they don't exist."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _migrate_from_pid_files(self, config_dir: Path) -> None:
        """One-time migration from legacy proxy.pid / proxy2.pid files."""
        if self.path.exists():
            return

        tunnels = []
        for pid_file in sorted(config_dir.glob("proxy*.pid")):
            if pid_file.name.endswith(".stop"):
                continue
            try:
                pid = int(pid_file.read_text().strip())
                # Derive index from filename: proxy.pid -> 0, proxy2.pid -> 1
                suffix = pid_file.stem.replace("proxy", "")
                idx = int(suffix) - 1 if suffix else 0
                port = 1080 + idx
                tunnels.append({
                    "id": f"ssh-{port}",
                    "kind": "ssh",
                    "codespace_name": "",
                    "port": port,
                    "pid": pid,
                    "status": "unknown",
                    "created": 0,
                    "failures": 0,
                    "last_failure": 0,
                })
            except (ValueError, OSError):
                continue

        if tunnels:
            self.save({"version": 1, "tunnels": tunnels})
            # Clean up old pid files so we never migrate again
            for f in list(config_dir.glob("proxy*.pid")) + list(config_dir.glob("proxy*.stop")):
                f.unlink(missing_ok=True)
        else:
            self.save({"version": 1, "tunnels": []})

    def _read(self) -> dict:
        """Read state from disk. Returns a safe default if the file is missing or corrupt."""
        if not self.path.exists():
            return {"version": 1, "tunnels": []}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "tunnels": []}

    def _write(self, data: dict) -> None:
        """Atomically write state to disk using a temp file + os.replace."""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=str(self.path.parent), delete=False, suffix=".tmp"
        )
        try:
            json.dump(data, tmp, indent=2)
            tmp.close()
            os.replace(tmp.name, str(self.path))
        except Exception:
            tmp.close()
            Path(tmp.name).unlink(missing_ok=True)
            raise

    def _acquire_lock(self, timeout: float = 5.0) -> None:
        """
        Acquire an advisory lock using atomic file creation.

        Uses os.O_CREAT | os.O_EXCL which is atomic on POSIX and Windows NTFS.
        If the lock file already exists, we check whether the owning process is
        still alive (via the PID stored inside). Dead locks are force-broken.
        As a fallback for network drives where O_EXCL may be unreliable, locks
        older than 30 seconds are also considered stale.
        """
        start = time.time()
        my_pid = os.getpid()
        while True:
            try:
                fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(fd, str(my_pid).encode())
                os.close(fd)
                return
            except FileExistsError:
                # Stale lock detection: by PID and by mtime
                try:
                    lock_pid = int(self._lock_path.read_text().strip())
                    stale_by_age = (
                        time.time() - self._lock_path.stat().st_mtime > 30
                    )
                    if lock_pid != my_pid and (not _pid_exists(lock_pid) or stale_by_age):
                        self._lock_path.unlink(missing_ok=True)
                        continue
                except (ValueError, OSError):
                    self._lock_path.unlink(missing_ok=True)
                    continue

                if time.time() - start > timeout:
                    raise TimeoutError(
                        f"Could not acquire state lock ({self._lock_path}). "
                        "Another cs-proxy process may be running."
                    )
                time.sleep(0.05)

    def _release_lock(self) -> None:
        """Release the advisory lock."""
        self._lock_path.unlink(missing_ok=True)

    def load(self) -> dict:
        """Load state under lock."""
        self._acquire_lock()
        try:
            return self._read()
        finally:
            self._release_lock()

    def save(self, data: dict) -> None:
        """Save state under lock."""
        self._acquire_lock()
        try:
            self._write(data)
        finally:
            self._release_lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reconcile(self) -> list[dict]:
        """
        Mark dead tunnels as crashed and return the list of newly-crashed entries.

        Call this on every CLI startup so stale state from previous runs is cleaned up.
        """
        data = self.load()
        changed = False
        crashed = []
        for t in data.get("tunnels", []):
            if t.get("status") in ("stopped", "crashed", "dead"):
                continue
            pid = t.get("pid")
            alive = _pid_exists(pid) if pid else False
            if not alive:
                t["status"] = "crashed"
                crashed.append(t)
                changed = True
        if changed:
            self.save(data)
        return crashed

    def clear_all(self) -> None:
        """Remove all tunnels from state."""
        data = self.load()
        data["tunnels"] = []
        self.save(data)

    def get_tunnels(
        self, kind: Optional[str] = None, status: Optional[str] = None
    ) -> list[dict]:
        """Return all tunnels, optionally filtered by kind and/or status."""
        data = self.load()
        tunnels = list(data.get("tunnels", []))
        if kind:
            tunnels = [t for t in tunnels if t.get("kind") == kind]
        if status:
            tunnels = [t for t in tunnels if t.get("status") == status]
        return tunnels

    def get_tunnel_by_port(self, port: int) -> Optional[dict]:
        """Return the tunnel dict for the given port, or None."""
        for t in self.get_tunnels():
            if t.get("port") == port:
                return t
        return None

    def add_tunnel(self, **fields: Any) -> None:
        """Add or replace a tunnel entry by its 'id'."""
        data = self.load()
        tunnels = [t for t in data.get("tunnels", []) if t.get("id") != fields.get("id")]
        tunnels.append(fields)
        data["tunnels"] = tunnels
        self.save(data)

    def remove_tunnel(
        self, port: Optional[int] = None, tunnel_id: Optional[str] = None
    ) -> None:
        """Remove a tunnel by port and/or tunnel_id."""
        data = self.load()
        tunnels = data.get("tunnels", [])
        if port is not None:
            tunnels = [t for t in tunnels if t.get("port") != port]
        if tunnel_id is not None:
            tunnels = [t for t in tunnels if t.get("id") != tunnel_id]
        data["tunnels"] = tunnels
        self.save(data)

    def update_tunnel(self, port: int, **kwargs: Any) -> None:
        """Update fields for the tunnel matching the given port."""
        data = self.load()
        for t in data.get("tunnels", []):
            if t.get("port") == port:
                t.update(kwargs)
                break
        self.save(data)

    def mark_crashed(self, port: int) -> None:
        """Convenience wrapper to mark a tunnel as crashed."""
        self.update_tunnel(port, status="crashed")

    def record_failure(
        self, port: int, max_failures: int = 3, window: int = 600
    ) -> bool:
        """
        Record a health-check failure for the tunnel on the given port.

        Returns True if the circuit breaker tripped (status set to 'dead').
        """
        data = self.load()
        for t in data.get("tunnels", []):
            if t.get("port") == port:
                now = int(time.time())
                last = t.get("last_failure", 0)
                if now - last > window:
                    t["failures"] = 0
                t["failures"] = t.get("failures", 0) + 1
                t["last_failure"] = now
                if t["failures"] >= max_failures:
                    t["status"] = "dead"
                self.save(data)
                return t["status"] == "dead"
        return False
