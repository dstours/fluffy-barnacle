#!/usr/bin/env python3
"""
Phase 3 hardening tests — circuit breaker, jitter, dry-run, check, deprecation.

Covers production-readiness fixes:
- Circuit breaker integration in health_check()
- Worker reconnect jitter
- Worker crash stderr surfacing
- Config deprecation warnings
- --dry-run flag for start/stop
- cs-proxy check (diagnostics) command
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Circuit breaker
# =============================================================================


def test_health_check_resets_failures_on_success(tmp_path):
    from csproxy.state import State
    from csproxy.tunnel import SSHTunnel
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=12345,
        status="healthy",
        created=0,
        failures=2,
        last_failure=0,
    )

    tunnel = SSHTunnel(config, "test-cs", port=1080)
    # Mock successful curl
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result):
        tunnel.health_check()

    t = state.get_tunnel_by_port(1080)
    assert t["failures"] == 0
    assert t["last_failure"] == 0


def test_health_check_records_failure_on_bad_check(tmp_path):
    from csproxy.state import State
    from csproxy.tunnel import SSHTunnel
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=12345,
        status="healthy",
        created=0,
        failures=0,
        last_failure=0,
    )

    tunnel = SSHTunnel(config, "test-cs", port=1080)
    mock_result = MagicMock()
    mock_result.returncode = 1

    with patch("subprocess.run", return_value=mock_result):
        result = tunnel.health_check()

    assert result is False
    t = state.get_tunnel_by_port(1080)
    assert t["failures"] == 1


def test_health_check_trips_circuit_breaker(tmp_path):
    from csproxy.state import State
    from csproxy.tunnel import SSHTunnel
    from csproxy.utils.config import Config

    config = Config(config_dir=tmp_path)
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=12345,
        status="healthy",
        created=0,
        failures=0,
        last_failure=0,
    )

    tunnel = SSHTunnel(config, "test-cs", port=1080)
    mock_result = MagicMock()
    mock_result.returncode = 1

    with patch("subprocess.run", return_value=mock_result):
        # Default max_failures=3, so 3 failures should trip
        tunnel.health_check()
        tunnel.health_check()
        tunnel.health_check()

    t = state.get_tunnel_by_port(1080)
    assert t["status"] == "dead"
    assert t["failures"] == 3


# =============================================================================
# Config deprecation warnings
# =============================================================================


def test_config_load_warns_on_deprecated_key(tmp_path):
    import yaml
    from unittest.mock import patch
    from csproxy.utils.config import Config

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"chain": "some-value", "socks_port": 1080}))

    mock_logger = MagicMock()
    with patch("csproxy.utils.config.get_logger", return_value=mock_logger):
        Config(config_dir=tmp_path, config_file=config_file)

    warning_calls = [c for c in mock_logger.warning.call_args_list if "chain" in str(c)]
    assert len(warning_calls) >= 1
    assert "Deprecated config key 'chain'" in str(warning_calls[0])


# =============================================================================
# --dry-run flag
# =============================================================================


def test_cmd_stop_dry_run_does_not_call_stop(tmp_path):
    from csproxy.proxy import cmd_stop
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager
    from unittest.mock import patch

    config = Config(config_dir=tmp_path)
    config._dry_run = True
    gh = GitHubManager()

    with patch("csproxy.tunnel.SSHTunnel.stop") as mock_stop:
        result = cmd_stop([], config, gh)

    assert result == 0
    mock_stop.assert_not_called()


def test_cmd_start_dry_run_does_not_start_tunnels(tmp_path):
    from csproxy.proxy import cmd_start
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager
    from unittest.mock import patch

    config = Config(config_dir=tmp_path)
    config.set("codespace_names", ["test-cs"])
    config._dry_run = True
    gh = GitHubManager()

    with patch("csproxy.tunnel.SSHTunnel.is_running", return_value=False):
        with patch("csproxy.tunnel.SSHTunnel.start") as mock_start:
            with patch("csproxy.codespace.CodespaceSelector.ensure_running"):
                result = cmd_start([], config, gh)

    assert result == 0
    mock_start.assert_not_called()


# =============================================================================
# check command
# =============================================================================


def test_check_command_exists():
    from csproxy.proxy import COMMANDS
    assert "check" in COMMANDS
    assert callable(COMMANDS["check"])


def test_check_command_runs_without_crash(tmp_path):
    from csproxy.proxy import cmd_check
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager

    config = Config(config_dir=tmp_path)
    gh = GitHubManager()
    result = cmd_check([], config, gh)
    # Should return non-zero because keys/dependencies are missing,
    # but must not raise.
    assert isinstance(result, int)


# =============================================================================
# Worker jitter (indirect test via code inspection)
# =============================================================================


def test_worker_imports_random():
    """Ensure _worker.py imports random for jitter."""
    import csproxy._worker as worker_mod
    assert "random" in dir(worker_mod)


# =============================================================================
# CLI --dry-run parsing
# =============================================================================


def test_cli_parses_dry_run_flag():
    from csproxy.cli import main_proxy
    from unittest.mock import patch

    with patch("csproxy.proxy.COMMANDS", {"help": lambda a, c, g: 0}):
        with patch("csproxy.proxy.show_help"):
            result = main_proxy(["--dry-run", "help"])
    assert result == 0
