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
from unittest.mock import patch

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
