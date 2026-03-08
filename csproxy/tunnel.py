#!/usr/bin/env python3
"""
SSH tunnel and HTTP proxy management.

Contains SSHTunnel (SOCKS5 via SSH) and HTTPProxyManager (tinyproxy with
SOCKS upstream). Extracted from proxy.py for modularity.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .utils import Config, ProxyError, SSHTunnelError, get_logger


class SSHTunnel:
    """
    Manages SSH SOCKS5 tunnel to a GitHub Codespace.

    Spawns an SSH process in the background with auto-reconnect logic
    using exponential backoff, mirroring the subshell loop in cs-proxy.sh.
    """

    def __init__(self, config: Config, codespace_name: str):
        self.config = config
        self.codespace_name = codespace_name
        self.logger = get_logger()
        self.pid_file = config.config_dir / 'proxy.pid'
        self.stop_file = config.config_dir / 'proxy.pid.stop'
        self.log_file = config.config_dir / 'proxy.log'
        self._process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        """
        Start SSH tunnel with SOCKS5 forwarding and auto-reconnect.

        Raises:
            SSHTunnelError: If tunnel cannot be established
        """
        if self.is_running():
            self.logger.warning(f"Proxy already running (PID: {self._read_pid()})")
            return

        self.logger.info(f"Starting SOCKS5 proxy on port {self.config.socks_port}...")

        if self.stop_file.exists():
            self.stop_file.unlink()

        ssh_args = [
            '--',
            '-D', f'127.0.0.1:{self.config.socks_port}',
            '-N',
            '-o', 'ServerAliveInterval=30',
            '-o', 'ServerAliveCountMax=3',
            '-o', 'ExitOnForwardFailure=yes',
        ]

        gh_cmd = ['gh', 'codespace', 'ssh', '--codespace', self.codespace_name] + ssh_args

        pid = os.fork() if hasattr(os, 'fork') else None

        if pid is not None:
            if pid == 0:
                self._run_with_reconnect(gh_cmd)
                sys.exit(0)
            else:
                self._write_pid(pid)
        else:
            self._run_windows_background(gh_cmd)

        self.logger.info("Waiting for tunnel to establish...")
        deadline = time.time() + 30
        while time.time() < deadline:
            time.sleep(3)
            if not self.is_running():
                raise SSHTunnelError("Tunnel process exited immediately - check logs")
            if self.health_check():
                break
        else:
            self.stop()
            raise SSHTunnelError(
                f"Tunnel started but proxy is not responding on port {self.config.socks_port}"
            )

        self.logger.info("SOCKS5 proxy started successfully")
        self.logger.info(f"  Local endpoint: socks5://127.0.0.1:{self.config.socks_port}")

    def _run_with_reconnect(self, gh_cmd: list) -> None:
        """Run SSH tunnel with exponential backoff reconnect."""
        delay = self.config.reconnect_delay

        while True:
            if self.stop_file.exists():
                self.stop_file.unlink()
                break

            log_mode = 'a' if self.log_file.exists() else 'w'
            with open(self.log_file, log_mode) as log_fd:
                process = subprocess.run(
                    gh_cmd,
                    stdout=log_fd,
                    stderr=log_fd,
                )

            if self.stop_file.exists():
                self.stop_file.unlink()
                break

            with open(self.log_file, 'a') as log_fd:
                log_fd.write(
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"SSH tunnel disconnected (exit: {process.returncode}). "
                    f"Reconnecting in {delay}s...\n"
                )

            time.sleep(delay)
            delay = min(delay * 2, self.config.max_reconnect_delay)

    def _run_windows_background(self, gh_cmd: list) -> None:
        """Start tunnel in background thread on Windows (no fork available)."""
        import threading

        def run():
            self._run_with_reconnect(gh_cmd)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self._write_pid(os.getpid())

    def stop(self) -> None:
        """Stop the SSH tunnel."""
        self.stop_file.touch()

        pid = self._read_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            except ProcessLookupError:
                pass

        if self.pid_file.exists():
            self.pid_file.unlink()

        try:
            subprocess.run(
                ['pkill', '-f', f'gh codespace ssh.*-D.*{self.config.socks_port}'],
                capture_output=True
            )
        except FileNotFoundError:
            pass

        self.logger.info("Proxy stopped")

    def is_running(self) -> bool:
        """Check if the tunnel process is still alive."""
        pid = self._read_pid()
        if not pid:
            return False

        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def health_check(self, timeout: int = 5) -> bool:
        """Verify the SOCKS5 proxy is responding."""
        result = subprocess.run(
            [
                'curl', '-s',
                '--connect-timeout', str(timeout),
                '--socks5-hostname', f'127.0.0.1:{self.config.socks_port}',
                'https://ifconfig.me'
            ],
            capture_output=True,
            timeout=timeout + 5
        )
        return result.returncode == 0

    def get_exit_ip(self) -> Optional[str]:
        """Get the exit IP address through the proxy."""
        result = subprocess.run(
            [
                'curl', '-s',
                '--connect-timeout', '5',
                '--socks5-hostname', f'127.0.0.1:{self.config.socks_port}',
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
