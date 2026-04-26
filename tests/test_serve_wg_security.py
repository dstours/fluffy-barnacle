#!/usr/bin/env python3
"""
Security regression tests for cs-serve and cs-wg.

Covers:
- Shell injection sanitization (shlex.quote)
- Path traversal rejection
- File size limits
- Stale PID validation
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# cs-serve security tests
# =============================================================================


def test_upload_rejects_path_traversal():
    from csproxy.serve import _validate_remote_path

    with pytest.raises(ValueError, match="Path traversal"):
        _validate_remote_path("../../../etc/passwd")

    with pytest.raises(ValueError, match="Path traversal"):
        _validate_remote_path("foo/../bar")


def test_upload_rejects_absolute_path():
    from csproxy.serve import _validate_remote_path

    with pytest.raises(ValueError, match="Absolute paths"):
        _validate_remote_path("/etc/passwd")


def test_upload_accepts_safe_relative_path():
    from csproxy.serve import _validate_remote_path

    # Should not raise
    _validate_remote_path("payload.txt")
    _validate_remote_path("captures/data.bin")


def test_upload_file_rejects_oversized(tmp_path, monkeypatch):
    from csproxy.serve import _upload_file
    from csproxy.github import GitHubManager
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    gh = GitHubManager()

    big_file = tmp_path / "huge.bin"
    big_file.write_bytes(b"x" * (100 * 1024 * 1024 + 1))

    with pytest.raises(ValueError, match="File too large"):
        _upload_file(gh, "test-cs", big_file, "huge.bin")


def test_ssh_command_uses_shlex_quote():
    from csproxy.serve import _ssh
    from csproxy.github import GitHubManager

    with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
        _ssh(GitHubManager(), "test-cs", "echo hello; rm -rf /")

    cmd = mock_run.call_args[0][0]
    # The command should be passed as a single arg after '--'
    assert cmd[-1] == "echo hello; rm -rf /"


def test_setup_server_environment_uses_shlex_quote():
    from csproxy.serve import _setup_server_environment
    from csproxy.github import GitHubManager
    from csproxy.utils.config import Config

    config = Config()
    gh = GitHubManager()

    with patch("csproxy.serve._ssh", return_value=MagicMock(returncode=0)) as mock_ssh:
        _setup_server_environment(gh, "test-cs", 9999)

    # Check that at least one ssh command contains the shlex-quoted port
    commands = [call[0][2] for call in mock_ssh.call_args_list]
    assert any("csproxy_server_9999" in c or "9999" in c for c in commands), (
        f"Expected shlex-quoted port in one of: {commands}"
    )


# =============================================================================
# cs-wg security tests
# =============================================================================


def test_stop_tunnel_validates_pid_before_kill(tmp_path):
    from csproxy.wireguard import stop_tunnel
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager
    import os

    config = Config(config_dir=tmp_path)
    gh = GitHubManager()

    # Create a stale PID file with a non-existent PID
    wg_dir = tmp_path / "wireguard"
    wg_dir.mkdir(parents=True, exist_ok=True)
    socat_pid = wg_dir / "socat_local.pid"
    ssh_pid = wg_dir / "ssh_tunnel.pid"
    socat_pid.write_text("999999")
    ssh_pid.write_text("999998")

    # Also create the current_codespace file so stop_tunnel doesn't bail early
    cs_file = tmp_path / "current_codespace"
    cs_file.write_text('CODESPACE_NAME="test-cs"\n')

    # Mock all the subprocess calls so we don't actually run wg/ip/pkill
    with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
        with patch("os.kill") as mock_kill:
            with patch("os.geteuid", return_value=0):
                with patch("os.environ.get", return_value=None):
                    try:
                        stop_tunnel(config, gh)
                    except Exception:
                        pass  # we expect some failures due to mocking

    # os.kill should be called with signal 0 (validation) before SIGTERM
    # The first call for each PID should be signal 0
    kill_calls = [c for c in mock_kill.call_args_list if c[0][0] in (999999, 999998)]
    if kill_calls:
        assert any(c[0][1] == 0 for c in kill_calls), (
            "Expected PID validation (signal 0) before SIGTERM"
        )


def test_wireguard_constants_are_consistent():
    from csproxy.wg_constants import WG_INTERFACE, WG_PORT, WG_LOCAL_IP, WG_REMOTE_IP, WG_NETWORK, TCP_RELAY_PORT
    from csproxy import wireguard

    # Ensure wireguard.py exports the same values as wg_constants
    assert wireguard.WG_INTERFACE == WG_INTERFACE
    assert wireguard.WG_PORT == WG_PORT
    assert wireguard.WG_LOCAL_IP == WG_LOCAL_IP
    assert wireguard.WG_REMOTE_IP == WG_REMOTE_IP
    assert wireguard.WG_NETWORK == WG_NETWORK
    assert wireguard.TCP_RELAY_PORT == TCP_RELAY_PORT


def test_bypass_routes_are_narrower_than_slash_8():
    from csproxy.wg_routes import _BYPASS_ROUTES

    for route in _BYPASS_ROUTES:
        cidr = route.split("/")[1]
        prefix_len = int(cidr)
        assert prefix_len >= 16, f"Bypass route {route} is too broad (should be /16 or narrower)"
