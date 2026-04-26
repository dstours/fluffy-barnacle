#!/usr/bin/env python3
"""
Phase 2 feature tests - Config dataclass, profiles, rotation, completion, PAC, state.

These tests verify the UX improvements added in Phase 2:
- Dataclass-based Config with validation and profiles
- Smart proxy rotation via _get_proxy_port
- Shell completion generator
- PAC command output
- State module basics
- New CLI commands (pac, completion)
"""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# =============================================================================
# Config dataclass + validation + profiles
# =============================================================================


def test_config_data_validation_rejects_low_port():
    from csproxy.utils.config import _ConfigData
    with pytest.raises(ValueError, match="socks_port must be 1024-65535"):
        _ConfigData(socks_port=80)


def test_config_data_validation_rejects_high_port():
    from csproxy.utils.config import _ConfigData
    with pytest.raises(ValueError, match="socks_port must be 1024-65535"):
        _ConfigData(socks_port=70000)


def test_config_data_validation_rejects_too_many_proxies():
    from csproxy.utils.config import _ConfigData
    with pytest.raises(ValueError, match="num_proxies must be 1-5"):
        _ConfigData(num_proxies=10)


def test_config_data_validation_rejects_zero_proxies():
    from csproxy.utils.config import _ConfigData
    with pytest.raises(ValueError, match="num_proxies must be 1-5"):
        _ConfigData(num_proxies=0)


def test_config_data_validation_rejects_bad_delay():
    from csproxy.utils.config import _ConfigData
    with pytest.raises(ValueError, match="reconnect_delay must be >= 1"):
        _ConfigData(reconnect_delay=0)


def test_config_data_validation_rejects_inconsistent_max_delay():
    from csproxy.utils.config import _ConfigData
    with pytest.raises(ValueError, match="max_reconnect_delay must be >= reconnect_delay"):
        _ConfigData(reconnect_delay=10, max_reconnect_delay=5)


def test_config_data_profile_merge():
    from csproxy.utils.config import _ConfigData
    raw = {
        "profile": "redteam",
        "profiles": {
            "redteam": {"socks_port": 9090, "num_proxies": 2},
            "stealth": {"dns_proxy": True},
        },
        "socks_port": 1080,
        "dns_proxy": False,
    }
    cfg = _ConfigData.from_dict(raw)
    assert cfg.socks_port == 9090
    assert cfg.num_proxies == 2
    assert cfg.dns_proxy is False  # not overridden by profile


def test_config_data_profile_ignored_when_not_found():
    from csproxy.utils.config import _ConfigData
    raw = {"profile": "nonexistent", "socks_port": 1080}
    cfg = _ConfigData.from_dict(raw)
    assert cfg.socks_port == 1080


def test_config_data_set_field_revalidates():
    from csproxy.utils.config import _ConfigData
    cfg = _ConfigData(socks_port=1080)
    cfg.set_field("socks_port", 9090)
    assert cfg.socks_port == 9090
    with pytest.raises(ValueError):
        cfg.set_field("socks_port", 80)


def test_config_data_set_field_rejects_unknown_key():
    from csproxy.utils.config import _ConfigData
    cfg = _ConfigData()
    with pytest.raises(KeyError, match="Unknown config key"):
        cfg.set_field("nonexistent", 1)


def test_config_env_override_socks_port(monkeypatch, tmp_path):
    from csproxy.utils.config import Config
    monkeypatch.setenv("SOCKS_PORT", "9999")
    config = Config(config_dir=tmp_path)
    assert config.socks_port == 9999


def test_config_env_override_locations(monkeypatch, tmp_path):
    from csproxy.utils.config import Config
    monkeypatch.setenv("LOCATIONS", "WestEurope,EastUs")
    config = Config(config_dir=tmp_path)
    assert config.locations == ["WestEurope", "EastUs"]


def test_config_env_override_bool(monkeypatch, tmp_path):
    from csproxy.utils.config import Config
    monkeypatch.setenv("DNS_PROXY", "true")
    config = Config(config_dir=tmp_path)
    assert config.dns_proxy is True


def test_config_save_and_load_preserve_unknown_keys(tmp_path):
    from csproxy.utils.config import Config
    config = Config(config_dir=tmp_path)
    config._extra["custom_key"] = "custom_value"
    config.save()

    config2 = Config(config_dir=tmp_path)
    assert config2._extra.get("custom_key") == "custom_value"


def test_config_save_and_load_preserve_profiles(tmp_path):
    from csproxy.utils.config import Config
    config = Config(config_dir=tmp_path)
    config.set("profile", "test")
    config.set("profiles", {"test": {"socks_port": 7777}})
    config.save()

    config2 = Config(config_dir=tmp_path)
    assert config2.get("profiles") == {"test": {"socks_port": 7777}}


# =============================================================================
# Proxy rotation
# =============================================================================


def test_get_proxy_port_fallback_when_no_state(monkeypatch, tmp_path):
    from csproxy.utils.config import Config
    from csproxy.tools import _get_proxy_port
    config = Config(config_dir=tmp_path)
    assert _get_proxy_port(config) == 1080


def test_get_proxy_port_uses_healthy_tunnel(monkeypatch, tmp_path):
    from csproxy.utils.config import Config
    from csproxy.tools import _get_proxy_port
    from csproxy.state import State

    config = Config(config_dir=tmp_path)
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1081",
        kind="ssh",
        codespace_name="test-cs",
        port=1081,
        pid=99999,
        status="healthy",
        created=0,
        failures=0,
        last_failure=0,
    )
    port = _get_proxy_port(config)
    assert port == 1081


def test_get_proxy_port_fallback_when_no_healthy_tunnels(monkeypatch, tmp_path):
    from csproxy.utils.config import Config
    from csproxy.tools import _get_proxy_port
    from csproxy.state import State

    config = Config(config_dir=tmp_path)
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1081",
        kind="ssh",
        codespace_name="test-cs",
        port=1081,
        pid=99999,
        status="crashed",
        created=0,
        failures=0,
        last_failure=0,
    )
    port = _get_proxy_port(config)
    assert port == 1080  # falls back to config default


# =============================================================================
# Shell completion generator
# =============================================================================


def test_bash_completion_contains_all_commands():
    from csproxy.completion import generate_completion
    script = generate_completion("bash")
    for cmd in ("start", "stop", "status", "pac", "completion", "help"):
        assert cmd in script, f"Missing command in bash completion: {cmd}"
    assert "complete -F" in script


def test_zsh_completion_contains_all_commands():
    from csproxy.completion import generate_completion
    script = generate_completion("zsh")
    for cmd in ("start", "stop", "status", "pac", "completion", "help"):
        assert cmd in script, f"Missing command in zsh completion: {cmd}"
    assert "_describe" in script


def test_completion_rejects_unsupported_shell():
    from csproxy.completion import generate_completion
    script = generate_completion("fish")
    assert "Unsupported shell" in script


def test_completion_is_case_insensitive():
    from csproxy.completion import generate_completion
    assert "complete -F" in generate_completion("BASH")
    assert "#compdef" in generate_completion("Zsh")


# =============================================================================
# PAC command
# =============================================================================


def test_cmd_pac_contains_socks_port():
    from csproxy.proxy import cmd_pac
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager
    import io

    config = Config()
    gh = GitHubManager()
    captured = io.StringIO()
    with patch("sys.stdout", new=captured):
        result = cmd_pac([], config, gh)
    assert result == 0
    output = captured.getvalue()
    assert "SOCKS5 127.0.0.1:" in output
    assert "DIRECT" in output
    assert "function FindProxyForURL" in output


def test_cmd_pac_uses_config_port():
    from csproxy.proxy import cmd_pac
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager
    import io

    config = Config()
    config.set("socks_port", 9999)
    gh = GitHubManager()
    captured = io.StringIO()
    with patch("sys.stdout", new=captured):
        cmd_pac([], config, gh)
    output = captured.getvalue()
    assert "127.0.0.1:9999" in output


# =============================================================================
# Completion command
# =============================================================================


def test_cmd_completion_bash():
    from csproxy.proxy import cmd_completion
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager
    import io

    config = Config()
    gh = GitHubManager()
    captured = io.StringIO()
    with patch("sys.stdout", new=captured):
        result = cmd_completion(["bash"], config, gh)
    assert result == 0
    assert "complete -F" in captured.getvalue()


def test_cmd_completion_unsupported_shell():
    from csproxy.proxy import cmd_completion
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager

    config = Config()
    gh = GitHubManager()
    result = cmd_completion(["fish"], config, gh)
    assert result == 1


# =============================================================================
# State module basics
# =============================================================================


def test_state_init_creates_dir(tmp_path):
    from csproxy.state import State
    subdir = tmp_path / "state_test"
    state = State(subdir)
    assert subdir.exists()


def test_state_add_and_get_tunnel(tmp_path):
    from csproxy.state import State
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=12345,
        status="starting",
        created=0,
        failures=0,
        last_failure=0,
    )
    tunnels = state.get_tunnels(kind="ssh")
    assert len(tunnels) == 1
    assert tunnels[0]["port"] == 1080


def test_state_remove_tunnel(tmp_path):
    from csproxy.state import State
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=12345,
        status="starting",
        created=0,
        failures=0,
        last_failure=0,
    )
    state.remove_tunnel(tunnel_id="ssh-1080")
    assert state.get_tunnels(kind="ssh") == []


def test_state_update_tunnel(tmp_path):
    from csproxy.state import State
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=12345,
        status="starting",
        created=0,
        failures=0,
        last_failure=0,
    )
    state.update_tunnel(1080, status="healthy")
    t = state.get_tunnel_by_port(1080)
    assert t["status"] == "healthy"


def test_state_reconcile_marks_dead_pid_as_crashed(tmp_path):
    from csproxy.state import State
    state = State(tmp_path)
    state.add_tunnel(
        id="ssh-1080",
        kind="ssh",
        codespace_name="test-cs",
        port=1080,
        pid=999999,  # non-existent PID
        status="healthy",
        created=0,
        failures=0,
        last_failure=0,
    )
    crashed = state.reconcile()
    assert len(crashed) == 1
    assert crashed[0]["status"] == "crashed"


def test_state_record_failure_tracks_failures(tmp_path):
    from csproxy.state import State
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
    # max_failures=3, window=600
    tripped = state.record_failure(1080, max_failures=3, window=600)
    assert tripped is False
    t = state.get_tunnel_by_port(1080)
    assert t["failures"] == 1


def test_state_record_failure_trips_circuit_breaker(tmp_path):
    from csproxy.state import State
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
    tripped = state.record_failure(1080, max_failures=2, window=600)
    assert tripped is False
    tripped = state.record_failure(1080, max_failures=2, window=600)
    assert tripped is True


# =============================================================================
# New CLI commands registered
# =============================================================================


def test_pac_command_in_dispatch_table():
    from csproxy.proxy import COMMANDS
    assert "pac" in COMMANDS
    assert callable(COMMANDS["pac"])


def test_completion_command_in_dispatch_table():
    from csproxy.proxy import COMMANDS
    assert "completion" in COMMANDS
    assert callable(COMMANDS["completion"])


def test_status_watch_flag_dispatches_to_watch_status():
    from csproxy.proxy import cmd_status
    from csproxy.utils.config import Config
    from csproxy.github import GitHubManager
    from unittest.mock import MagicMock

    config = Config()
    gh = GitHubManager()
    with patch("csproxy.display.watch_status") as mock_watch:
        result = cmd_status(["--watch"], config, gh)
    assert result == 0
    mock_watch.assert_called_once()


# =============================================================================
# cs-tools improvements (Phase 2 follow-up)
# =============================================================================


def test_check_proxy_caches_result():
    """check_proxy should cache the result for 5 seconds."""
    from csproxy.tools import check_proxy, _CHECK_CACHE

    # Clear cache
    _CHECK_CACHE.clear()

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        result1 = check_proxy('127.0.0.1', 1080, _bypass_cache=True)
        result2 = check_proxy('127.0.0.1', 1080)
        result3 = check_proxy('127.0.0.1', 1080)

    assert result1 is True
    assert result2 is True
    assert result3 is True
    # First call does subprocess.run, next two hit cache
    assert mock_run.call_count == 1


def test_check_proxy_bypass_cache():
    """_bypass_cache=True should always hit subprocess."""
    from csproxy.tools import check_proxy, _CHECK_CACHE

    _CHECK_CACHE.clear()

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        check_proxy('127.0.0.1', 1080)
        check_proxy('127.0.0.1', 1080, _bypass_cache=True)

    assert mock_run.call_count == 2


def test_proxy_env_sets_variables():
    """_proxy_env returns dict with SOCKS5 proxy variables."""
    from csproxy.tools import _proxy_env

    env = _proxy_env('127.0.0.1', 1080)
    assert env['ALL_PROXY'] == 'socks5h://127.0.0.1:1080'
    assert env['HTTP_PROXY'] == 'socks5h://127.0.0.1:1080'
    assert env['HTTPS_PROXY'] == 'socks5h://127.0.0.1:1080'
    assert env['SOCKS_PROXY'] == 'socks5h://127.0.0.1:1080'


def test_sanitize_nmap_args_removes_invalid_scans():
    """_sanitize_nmap_args strips scan types that don't work through SOCKS."""
    from csproxy.tools import _sanitize_nmap_args

    args = ['-sS', '-p', '80', '-sU', '-O', '--traceroute', '--scanflags', 'URG', 'target.com']
    with patch('os.geteuid', return_value=1000):
        result = _sanitize_nmap_args(args)

    assert '-sS' not in result
    assert '-sU' not in result
    assert '-O' not in result
    assert '--traceroute' not in result
    assert '--scanflags' not in result
    assert 'URG' not in result
    assert '-sT' in result
    assert '-Pn' in result
    assert 'target.com' in result
    assert '-p' in result
    assert '80' in result


def test_sanitize_nmap_args_adds_required_flags():
    """_sanitize_nmap_args prepends -sT and -Pn when missing."""
    from csproxy.tools import _sanitize_nmap_args

    with patch('os.geteuid', return_value=1000):
        result = _sanitize_nmap_args(['target.com'])

    assert result[0] == '-Pn'
    assert result[1] == '-sT'


def test_sanitize_nmap_args_adds_max_parallelism():
    """_sanitize_nmap_args adds --max-parallelism 10 when not present."""
    from csproxy.tools import _sanitize_nmap_args

    with patch('os.geteuid', return_value=1000):
        result = _sanitize_nmap_args(['target.com'])

    assert '--max-parallelism' in result
    assert result[result.index('--max-parallelism') + 1] == '10'


def test_sanitize_nmap_args_respects_existing_max_parallelism():
    """_sanitize_nmap_args does not override existing --max-parallelism."""
    from csproxy.tools import _sanitize_nmap_args

    with patch('os.geteuid', return_value=1000):
        result = _sanitize_nmap_args(['--max-parallelism', '5', 'target.com'])

    idx = result.index('--max-parallelism')
    assert result[idx + 1] == '5'


def test_main_tools_help():
    """main_tools(['help']) returns 0."""
    from csproxy.tools import main_tools
    assert main_tools(['help']) == 0


def test_main_tools_no_args():
    """main_tools([]) returns 0 (shows help)."""
    from csproxy.tools import main_tools
    assert main_tools([]) == 0


def test_main_tools_dry_run():
    """--dry-run prints command without executing."""
    from csproxy.tools import main_tools

    with patch('builtins.print') as mock_print:
        result = main_tools(['--dry-run', 'pcurl', 'https://example.com'])
    assert result == 0
    printed = ' '.join(str(c[0][0]) for c in mock_print.call_args_list)
    assert '[dry-run]' in printed


def test_main_tools_unknown_tool():
    """main_tools returns 1 for unknown tool."""
    from csproxy.tools import main_tools
    assert main_tools(['notatool']) == 1


def test_main_tools_timeout_passed_to_wrapper():
    """--timeout is forwarded to the tool wrapper."""
    from csproxy.tools import main_tools

    mock_pcurl = MagicMock(return_value=0)
    with patch.dict('csproxy.tools.TOOL_COMMANDS', {'pcurl': ('pcurl', mock_pcurl)}):
        with patch('csproxy.tools.check_proxy', return_value=True):
            main_tools(['--timeout', '99', 'pcurl', 'https://example.com'])

    mock_pcurl.assert_called_once()
    kwargs = mock_pcurl.call_args[1]
    assert kwargs['timeout'] == 99


def test_pcs_command_not_found():
    """pcs returns 127 when the wrapped command does not exist."""
    from csproxy.tools import pcs

    with patch('shutil.which', return_value=None):
        with patch('csproxy.tools.check_proxy', return_value=True):
            result = pcs(['nonexistent', 'arg'])

    assert result == 127
