#!/usr/bin/env python3
"""
SSH tunnel and HTTP proxy management.

Contains SSHTunnel (SOCKS5 via SSH) and HTTPProxyManager (tinyproxy with
SOCKS upstream). Extracted from proxy.py for modularity.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .state import State
from .utils import Config, ProxyError, SSHTunnelError, get_logger


class SSHTunnel:
    """
    Manages SSH SOCKS5 tunnel to a GitHub Codespace.

    Spawns an SSH process in the background with auto-reconnect logic
    using exponential backoff, mirroring the subshell loop in cs-proxy.sh.
    """

    def __init__(self, config: Config, codespace_name: str, *,
                 port: Optional[int] = None,
                 pid_suffix: str = ''):
        self.config = config
        self.codespace_name = codespace_name
        self.port = port or config.socks_port
        self.logger = get_logger()
        self.pid_file = config.config_dir / f'proxy{pid_suffix}.pid'
        self.stop_file = config.config_dir / f'proxy{pid_suffix}.pid.stop'
        self.log_file = config.config_dir / f'proxy{pid_suffix}.log'
        self.spec_file = config.config_dir / 'workers' / f'{self.port}.json'
        self.state = State(config.config_dir)
        self.tunnel_id = f'ssh-{self.port}'
        self._process: Optional[subprocess.Popen] = None

    def start(self, start_timeout: int = 30) -> None:
        """
        Start SSH tunnel with SOCKS5 forwarding and auto-reconnect.

        Spawns a detached subprocess worker that runs the reconnect loop,
        so the tunnel survives terminal death and works cross-platform.

        Args:
            start_timeout: Seconds to wait for the SOCKS5 listener to become healthy.
                           Additional tunnels use 90s since gh may take longer to
                           establish concurrent SSH relay sessions (default: 30).

        Raises:
            SSHTunnelError: If tunnel cannot be established
        """
        if self.is_running():
            self.logger.warning(f"Proxy already running on port {self.port}")
            return

        self.logger.info(f"Starting SOCKS5 proxy on port {self.port}...")
        self.stop_file.unlink(missing_ok=True)
        self.spec_file.parent.mkdir(parents=True, exist_ok=True)

        ssh_args = [
            '--',
            '-D', f'127.0.0.1:{self.port}',
            '-N',
            '-o', 'ServerAliveInterval=30',
            '-o', 'ServerAliveCountMax=3',
            '-o', 'ExitOnForwardFailure=yes',
            '-o', 'ControlMaster=no',
            '-o', 'ControlPath=none',
        ]

        gh_cmd = ['gh', 'codespace', 'ssh', '--codespace', self.codespace_name] + ssh_args

        spec = {
            'gh_cmd': gh_cmd,
            'log_file': str(self.log_file),
            'stop_file': str(self.stop_file),
            'reconnect_delay': self.config.reconnect_delay,
            'max_reconnect_delay': self.config.max_reconnect_delay,
        }
        self.spec_file.write_text(json.dumps(spec))

        worker_cmd = [sys.executable, '-m', 'csproxy._worker', str(self.spec_file)]

        popen_kwargs = {}
        if sys.platform == 'win32':
            popen_kwargs['creationflags'] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_kwargs['start_new_session'] = True

        # Redirect stderr to a file so we can surface it if the worker
        # crashes immediately (e.g., import error, bad spec).
        stderr_file = self.spec_file.with_suffix('.stderr')
        proc = subprocess.Popen(
            worker_cmd,
            stdout=subprocess.DEVNULL,
            stderr=open(stderr_file, 'w'),
            **popen_kwargs,
        )
        self._process = proc
        self._write_pid(proc.pid)

        # Quick verification: ensure the worker didn't crash immediately
        # and that it still has its spec file (proves it started reading it)
        time.sleep(0.3)
        if proc.poll() is not None:
            stderr_text = ""
            try:
                if stderr_file.exists():
                    stderr_text = stderr_file.read_text().strip()
                    stderr_file.unlink(missing_ok=True)
            except OSError:
                pass
            self.spec_file.unlink(missing_ok=True)
            msg = (
                f"Tunnel worker exited immediately with code {proc.returncode}. "
                f"Check that 'python -m csproxy._worker' is executable."
            )
            if stderr_text:
                msg += f" Worker stderr: {stderr_text[:500]}"
            raise SSHTunnelError(msg)
        if not self.spec_file.exists():
            raise SSHTunnelError(
                "Tunnel worker started but spec file was cleaned up unexpectedly."
            )

        self.state.add_tunnel(
            id=self.tunnel_id,
            kind='ssh',
            codespace_name=self.codespace_name,
            port=self.port,
            pid=proc.pid,
            status='starting',
            created=int(time.time()),
            failures=0,
            last_failure=0,
        )

        self.logger.info(f"Waiting for tunnel to establish (timeout: {start_timeout}s)...")
        deadline = time.time() + start_timeout
        attempt = 0
        while time.time() < deadline:
            time.sleep(3)
            attempt += 1
            if not self.is_running():
                self.state.mark_crashed(self.port)
                raise SSHTunnelError("Tunnel process exited immediately - check logs")
            self.logger.debug(f"Health check attempt {attempt} on port {self.port}...")
            if self.health_check():
                self.state.update_tunnel(self.port, status='healthy')
                break
        else:
            self.stop()
            raise SSHTunnelError(
                f"Tunnel not responding on port {self.port} after {start_timeout}s "
                f"— check logs: {self.log_file}"
            )

        self.logger.info("SOCKS5 proxy started successfully")
        self.logger.info(f"  Local endpoint: socks5://127.0.0.1:{self.port}")

    def stop(self) -> None:
        """Stop the SSH tunnel."""
        self.stop_file.touch()

        pid = self._read_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                # Poll for up to 2s for graceful exit
                for _ in range(20):
                    time.sleep(0.1)
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                else:
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        self.pid_file.unlink(missing_ok=True)
        self.spec_file.unlink(missing_ok=True)
        self.spec_file.with_suffix('.stderr').unlink(missing_ok=True)
        self.state.remove_tunnel(port=self.port)
        self.logger.info("Proxy stopped")

    def cleanup(self) -> None:
        """
        Aggressive cleanup: kill any lingering worker, remove all artifacts,
        and purge the state entry. Use when a tunnel is known to be stale.
        """
        self.logger.debug(f"Aggressive cleanup for tunnel :{self.port}")

        # Try to kill by PID file
        pid = self._read_pid()
        if pid:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.kill(pid, sig)
                    time.sleep(0.2)
                    os.kill(pid, 0)
                except (ProcessLookupError, PermissionError):
                    break

        # Kill any process still listening on our port (last resort)
        self._kill_port_holders()

        # Remove all artifacts
        self.pid_file.unlink(missing_ok=True)
        self.stop_file.unlink(missing_ok=True)
        self.spec_file.unlink(missing_ok=True)
        self.spec_file.with_suffix('.stderr').unlink(missing_ok=True)
        self.state.remove_tunnel(port=self.port)

    def _kill_port_holders(self) -> None:
        """Kill processes listening on our SOCKS port (platform-specific)."""
        try:
            if sys.platform == 'darwin':
                # lsof -ti:port gives PIDs
                result = subprocess.run(
                    ['lsof', '-ti', f':{self.port}'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    for pid_str in result.stdout.strip().splitlines():
                        try:
                            os.kill(int(pid_str), signal.SIGKILL)
                        except (ValueError, ProcessLookupError, PermissionError):
                            pass
            elif sys.platform == 'linux':
                result = subprocess.run(
                    ['fuser', '-k', f'{self.port}/tcp'],
                    capture_output=True, timeout=5
                )
        except Exception:
            pass

    def is_running(self) -> bool:
        """Check if the tunnel process is still alive."""
        # If state says dead/crashed, trust that over PID existence
        # (prevents zombies where worker is alive but circuit breaker tripped)
        state_tunnel = self.state.get_tunnel_by_port(self.port)
        if state_tunnel and state_tunnel.get('status') in ('dead', 'crashed'):
            self._cleanup_stale()
            return False

        pid = self._read_pid()
        if not pid:
            return False

        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            self._cleanup_stale()
            return False

    def _cleanup_stale(self) -> None:
        """Remove stale PID files and state entries for dead processes."""
        self.pid_file.unlink(missing_ok=True)
        self.spec_file.unlink(missing_ok=True)
        self.state.remove_tunnel(port=self.port)

    def health_check(self, timeout: int = 5) -> bool:
        """Verify the SOCKS5 proxy is responding."""
        result = subprocess.run(
            [
                'curl', '-s',
                '--connect-timeout', str(timeout),
                '--max-time', str(timeout + 2),
                '--socks5-hostname', f'127.0.0.1:{self.port}',
                'https://ifconfig.me'
            ],
            capture_output=True,
            timeout=timeout + 5
        )
        healthy = result.returncode == 0
        if healthy:
            # Reset failure counter on success
            self.state.update_tunnel(self.port, failures=0, last_failure=0)
        else:
            # Record failure and trip circuit breaker if threshold exceeded
            tripped = self.state.record_failure(self.port)
            if tripped:
                self.logger.warning(
                    f"Circuit breaker tripped for tunnel :{self.port}. "
                    f"Tunnel marked as dead — manual restart required."
                )
        return healthy

    def get_exit_ip(self) -> Optional[str]:
        """Get the exit IP address through the proxy."""
        result = subprocess.run(
            [
                'curl', '-s',
                '--connect-timeout', '5',
                '--socks5-hostname', f'127.0.0.1:{self.port}',
                'https://ifconfig.me'
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _write_pid(self, pid: int) -> None:
        """Write PID to PID file."""
        self.pid_file.write_text(str(pid))

    def _read_pid(self) -> Optional[int]:
        """Read PID from PID file."""
        if not self.pid_file.exists():
            return None
        try:
            return int(self.pid_file.read_text().strip())
        except (ValueError, OSError):
            return None


class HTTPProxyManager:
    """
    Manages HTTP proxy using tinyproxy as SOCKS5 upstream.

    Equivalent to start_http_proxy() in cs-proxy.sh.
    """

    def __init__(self, config: Config):
        self.config = config
        self.logger = get_logger()
        self.conf_file = config.config_dir / 'tinyproxy.conf'
        self.pid_file = config.config_dir / 'tinyproxy.pid'

    def _install_tinyproxy(self) -> None:
        """Attempt to install tinyproxy via apt-get."""
        self.logger.warning("tinyproxy not installed. Installing...")
        result = subprocess.run(
            ['sudo', 'apt-get', 'install', '-y', 'tinyproxy'],
            capture_output=True
        )
        if result.returncode != 0:
            raise ProxyError(
                "Failed to install tinyproxy. "
                "Install manually: sudo apt-get install tinyproxy"
            )

    def _write_config(self) -> None:
        """Write tinyproxy configuration file."""
        config_content = f"""# tinyproxy config for cs-proxy
# Generated on {time.strftime('%Y-%m-%d %H:%M:%S')}

User nobody
Group nogroup
Port {self.config.http_proxy_port}
Listen 127.0.0.1
Timeout 600
LogLevel Warning
MaxClients 100
MinSpareServers 2
MaxSpareServers 10
StartServers 5
MaxRequestsPerChild 0
Allow 127.0.0.1
ViaProxyName "tinyproxy"

# Upstream SOCKS5 proxy (the cs-proxy tunnel)
Upstream socks5 127.0.0.1:{self.config.socks_port}
"""
        self.conf_file.write_text(config_content)
        self.conf_file.chmod(0o600)

    def start(self) -> None:
        """Start HTTP proxy via tinyproxy."""
        if not shutil.which('tinyproxy'):
            self._install_tinyproxy()

        self._write_config()

        result = subprocess.run(
            ['tinyproxy', '-c', str(self.conf_file)],
            capture_output=True
        )

        if result.returncode != 0:
            raise ProxyError(
                f"tinyproxy failed to start: {result.stderr.decode().strip()}"
            )

        self.logger.info(f"HTTP proxy started on port {self.config.http_proxy_port}")

    def stop(self) -> None:
        """Stop tinyproxy if running."""
        try:
            subprocess.run(['pkill', 'tinyproxy'], capture_output=True)
        except FileNotFoundError:
            pass
