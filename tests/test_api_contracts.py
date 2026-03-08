#!/usr/bin/env python3
"""
API contract tests - verify all public symbols survive refactoring.

These tests ensure backward compatibility when modules are split.
Run before and after any refactoring step.
"""

import pytest
from unittest.mock import patch, MagicMock


def test_csproxy_package_exports():
    """All symbols in __all__ are importable from csproxy."""
    import csproxy
    expected = [
        'SSHTunnel', 'HTTPProxyManager', 'CodespaceSelector', 'ProxychainsConfig',
        'GitHubManager', 'Config', 'setup_logger', 'get_logger',
        'check_dependencies', 'CSProxyError',
        'check_proxy', 'ipcheck', 'pcurl', 'pwget', 'pnmap', 'pnuclei',
        'pffuf', 'phttpx', 'psqlmap', 'pcs', 'psub', 'pportscan',
    ]
    for name in expected:
        assert hasattr(csproxy, name), f"Missing from csproxy: {name}"


def test_proxy_module_exports():
    """proxy.py exports COMMANDS, show_help, and all classes."""
    from csproxy.proxy import (
        COMMANDS, SSHTunnel, HTTPProxyManager, CodespaceSelector,
        ProxychainsConfig, show_help,
    )
    assert callable(show_help)
    assert isinstance(COMMANDS, dict)

    # All expected command keys
    expected_commands = {
        'start', 'stop', 'restart', 'status', 'list', 'create',
        'set', 'http', 'proxychains', 'env', 'burp', 'keygen',
        'config', 'logs', 'split', 'ssh', 'run', 'name',
        'teardown', 'down', 'delete', 'rm', 'token', 'aliases', 'help',
    }
    assert expected_commands <= set(COMMANDS.keys())

    # All command handlers are callable with correct signature
    for name, handler in COMMANDS.items():
        assert callable(handler), f"COMMANDS[{name!r}] is not callable"


def test_serve_module_exports():
    """serve.py exports SERVE_COMMANDS and all serve functions."""
    from csproxy.serve import (
        SERVE_COMMANDS, DEFAULT_PORT,
        serve_file, serve_directory, serve_redirect, serve_custom,
        stop_server, clean_all, list_files, show_help,
    )
    expected = {'file', 'dir', 'redirect', 'custom', 'stop', 'clean', 'cleanup', 'list'}
    assert expected <= set(SERVE_COMMANDS.keys())
    assert DEFAULT_PORT == 9999


def test_wireguard_module_exports():
    """wireguard.py exports COMMANDS and WG constants."""
    from csproxy.wireguard import (
        COMMANDS, WG_INTERFACE, WG_PORT, WG_LOCAL_IP,
        WG_REMOTE_IP, WG_NETWORK, TCP_RELAY_PORT, show_help,
    )
    expected = {'up', 'down', 'status', 'route', 'monitor'}
    assert expected <= set(COMMANDS.keys())
    assert WG_PORT == 51820
    assert TCP_RELAY_PORT == 51821


def test_ssh_tunnel_init():
    """SSHTunnel can be initialized without side effects."""
    from csproxy.proxy import SSHTunnel
    from csproxy.utils import Config
    config = Config()
    tunnel = SSHTunnel(config, 'test-codespace')
    assert tunnel.codespace_name == 'test-codespace'
    assert tunnel.pid_file == config.config_dir / 'proxy.pid'


def test_codespace_selector_init():
    """CodespaceSelector can be initialized without side effects."""
    from csproxy.proxy import CodespaceSelector
    from csproxy.utils import Config
    from csproxy.github import GitHubManager
    config = Config()
    gh = GitHubManager()
    selector = CodespaceSelector(gh, config)
    assert selector.BLANK_REPO == 'github/codespaces-blank'


def test_cli_entry_points_importable():
    """CLI entry points are importable."""
    from csproxy.cli import main_proxy, main_serve, main_wg
    assert callable(main_proxy)
    assert callable(main_serve)
    assert callable(main_wg)


def test_serve_script_templates_compile():
    """Embedded server script templates produce valid Python."""
    import py_compile
    import tempfile
    import os

    from csproxy.serve import (
        _FILE_SERVER_SCRIPT, _REDIRECT_SERVER_SCRIPT, _CUSTOM_SERVER_SCRIPT
    )

    for name, template in [
        ('file_server', _FILE_SERVER_SCRIPT),
        ('redirect_server', _REDIRECT_SERVER_SCRIPT),
        ('custom_server', _CUSTOM_SERVER_SCRIPT),
    ]:
        script = template.format(
            PORT=9999, TARGET_URL='https://example.com',
            REDIRECT_CODE=302, RESPONSE_BODY='OK',
            CONTENT_TYPE='text/plain', STATUS_CODE=200,
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script)
            fname = f.name
        try:
            py_compile.compile(fname, doraise=True)
        finally:
            os.unlink(fname)


def test_wireguard_setup_script_renders():
    """WireGuard remote setup script template renders correctly."""
    from csproxy.wireguard import _REMOTE_SETUP_SCRIPT
    rendered = _REMOTE_SETUP_SCRIPT.format(
        remote_private_key='TEST_KEY=',
        wg_remote_ip='10.99.99.1/24',
        wg_port=51820,
        wg_network='10.99.99.0/24',
        local_public_key='TEST_PUB=',
        local_ip_host='10.99.99.2',
        remote_ip_host='10.99.99.1',
    )
    assert '#!/usr/bin/env bash' in rendered
    assert 'TEST_KEY=' in rendered


def test_health_check_uses_socks5_hostname():
    """health_check() must use --socks5-hostname to resolve DNS via proxy (issue #5)."""
    from csproxy.proxy import SSHTunnel
    from csproxy.utils import Config

    tunnel = SSHTunnel(Config(), 'test-codespace')
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        result = tunnel.health_check()

    args = mock_run.call_args[0][0]
    assert '--socks5-hostname' in args
    assert '--socks5' not in args
    assert result is True


def test_get_exit_ip_uses_socks5_hostname():
    """get_exit_ip() must use --socks5-hostname to resolve DNS via proxy (issue #5)."""
    from csproxy.proxy import SSHTunnel
    from csproxy.utils import Config

    tunnel = SSHTunnel(Config(), 'test-codespace')
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '1.2.3.4'

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        ip = tunnel.get_exit_ip()

    args = mock_run.call_args[0][0]
    assert '--socks5-hostname' in args
    assert '--socks5' not in args
    assert ip == '1.2.3.4'
