#!/usr/bin/env python3
"""
Test script to verify Phase 1 installation is working correctly.

Run this after installing the package to verify all components are functional.
"""

import sys
from pathlib import Path


def test_imports():
    """Test that all modules can be imported."""
    print("[*] Testing imports...")

    try:
        # Test main package
        import csproxy
        print(f"  [+] csproxy version: {csproxy.__version__}")

        # Test utilities
        from csproxy.utils import (
            CSProxyError,
            Config,
            check_dependencies,
            get_logger,
            setup_logger,
        )
        print("  [+] csproxy.utils")

        # Test GitHub module
        from csproxy.github import GitHubManager
        print("  [+] csproxy.github")

        # Test CLI module
        from csproxy import cli
        print("  [+] csproxy.cli")

        return True

    except ImportError as e:
        print(f"  [-] Import failed: {e}")
        return False


def test_logging():
    """Test logging functionality."""
    print("\n[*] Testing logging...")

    try:
        from csproxy.utils import setup_logger

        # Test basic logging
        logger = setup_logger(verbose=True)
        logger.info("Test INFO message")
        logger.warning("Test WARNING message")
        logger.debug("Test DEBUG message")
        # logger.error("Test ERROR message")  # Don't print error in test

        print("  [+] Logging works (check colored output above)")
        return True

    except Exception as e:
        print(f"  [-] Logging failed: {e}")
        return False


def test_config():
    """Test configuration management."""
    print("\n[*] Testing configuration...")

    try:
        from csproxy.utils import Config

        # Create config with defaults
        config = Config()

        # Test property access
        assert config.socks_port == 1080
        assert config.http_proxy_port == 8080
        assert isinstance(config.verbose, bool)

        print(f"  [+] Config defaults: SOCKS={config.socks_port}, HTTP={config.http_proxy_port}")

        # Test modification
        config.set('socks_port', 9050)
        assert config.socks_port == 9050

        print("  [+] Config modification works")
        return True

    except Exception as e:
        print(f"  [-] Config failed: {e}")
        return False


def test_github_manager():
    """Test GitHub manager initialization."""
    print("\n[*] Testing GitHub manager...")

    try:
        from csproxy.github import GitHubManager

        gh = GitHubManager()
        print("  [+] GitHubManager initialized")

        # Try to load token (won't fail if not present)
        token = gh.load_token()
        if token:
            print(f"  [+] GitHub token loaded (length: {len(token)})")
        else:
            print("  [i] No GitHub token found (this is OK)")

        return True

    except Exception as e:
        print(f"  [-] GitHub manager failed: {e}")
        return False


def test_dependencies():
    """Test dependency checking."""
    print("\n[*] Testing dependency checking...")

    try:
        from csproxy.utils import check_command, check_dependencies

        # Test command checking
        has_python = check_command('python3')
        print(f"  [+] check_command('python3') = {has_python}")

        # Test dependency checking (don't raise on missing)
        try:
            missing_req, missing_opt = check_dependencies(
                required=['gh', 'ssh', 'curl'],
                raise_on_missing=False
            )

            if not missing_req:
                print("  [+] All required dependencies found")
            else:
                print(f"  [!] Missing required: {missing_req}")

        except Exception as e:
            print(f"  [!] Dependency check raised: {e}")

        return True

    except Exception as e:
        print(f"  [-] Dependency checking failed: {e}")
        return False


def test_exceptions():
    """Test custom exceptions."""
    print("\n[*] Testing exceptions...")

    try:
        from csproxy.utils import (
            CSProxyError,
            CodespaceError,
            ConfigError,
            DependencyError,
            GitHubAuthError,
        )

        # Test exception creation
        err1 = CSProxyError("Test error")
        assert err1.exit_code == 1

        err2 = DependencyError(['gh', 'ssh'])
        assert 'gh' in err2.missing_deps

        err3 = CodespaceError("Test", codespace_name="test-cs")
        assert err3.codespace_name == "test-cs"

        print("  [+] All exception types work correctly")
        return True

    except Exception as e:
        print(f"  [-] Exception test failed: {e}")
        return False


def test_proxy_module():
    """Test Phase 2 proxy module imports and structure."""
    print("\n[*] Testing proxy module (Phase 2)...")

    try:
        # Test proxy module imports
        from csproxy.proxy import (
            COMMANDS,
            CodespaceSelector,
            HTTPProxyManager,
            ProxychainsConfig,
            SSHTunnel,
            cmd_env,
            cmd_help,
            cmd_status,
            show_help,
        )
        print("  [+] proxy.py classes imported")

        # Test all 24 commands are registered
        expected_commands = {
            'start', 'stop', 'restart', 'status', 'list', 'create',
            'set', 'http', 'proxychains', 'env', 'burp', 'keygen',
            'config', 'logs', 'split', 'ssh', 'run', 'name',
            'teardown', 'down', 'delete', 'rm', 'token', 'aliases',
            'pac', 'completion', 'check', 'help',
        }
        registered = set(COMMANDS.keys())
        missing = expected_commands - registered
        if missing:
            print(f"  [-] Missing commands: {missing}")
            return False
        print(f"  [+] All {len(registered)} commands registered")

        # Test SSHTunnel initialization (no OS calls)
        from csproxy.utils import Config
        config = Config()
        tunnel = SSHTunnel(config, 'test-codespace')
        assert tunnel.codespace_name == 'test-codespace'
        assert tunnel.pid_file == config.config_dir / 'proxy.pid'
        print("  [+] SSHTunnel initialization OK")

        # Test CodespaceSelector initialization
        from csproxy.github import GitHubManager
        gh = GitHubManager()
        selector = CodespaceSelector(gh, config)
        assert selector.BLANK_REPO == 'github/codespaces-blank'
        print("  [+] CodespaceSelector initialization OK")

        # Test CLI argument parsing (using in-process argv)
        from csproxy.cli import main_proxy
        # Help should return 0
        result = main_proxy(['help'])
        assert result == 0, f"Expected 0, got {result}"
        print("  [+] CLI dispatch to help works")

        return True

    except Exception as e:
        print(f"  [-] Proxy module test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_serve_module():
    """Test cs-serve module imports and structure."""
    print("\n[*] Testing serve module (cs-serve.sh conversion)...")

    try:
        from csproxy.serve import (
            SERVE_COMMANDS,
            DEFAULT_PORT,
            _FILE_SERVER_SCRIPT,
            _REDIRECT_SERVER_SCRIPT,
            _CUSTOM_SERVER_SCRIPT,
            serve_file,
            serve_directory,
            serve_redirect,
            serve_custom,
            stop_server,
            clean_all,
            list_files,
            show_help,
        )
        print("  [+] serve.py imported")

        # Verify all commands are registered
        expected = {'file', 'dir', 'redirect', 'custom', 'stop', 'clean', 'cleanup', 'list'}
        registered = set(SERVE_COMMANDS.keys())
        missing = expected - registered
        if missing:
            print(f"  [-] Missing serve commands: {missing}")
            return False
        print(f"  [+] All {len(registered)} serve commands registered")

        # Verify default port
        assert DEFAULT_PORT == 9999
        print(f"  [+] DEFAULT_PORT = {DEFAULT_PORT}")

        # Verify server scripts are valid Python by compiling them
        import py_compile, tempfile, os
        for name, script_template in [
            ('file_server', _FILE_SERVER_SCRIPT),
            ('redirect_server', _REDIRECT_SERVER_SCRIPT),
            ('custom_server', _CUSTOM_SERVER_SCRIPT),
        ]:
            # Fill in required placeholders with test values
            script = script_template.format(
                PORT=9999,
                TARGET_URL='https://example.com',
                REDIRECT_CODE=302,
                RESPONSE_BODY='OK',
                CONTENT_TYPE='text/plain',
                STATUS_CODE=200,
            )
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(script)
                fname = f.name
            try:
                py_compile.compile(fname, doraise=True)
                print(f"  [+] {name} script is valid Python")
            except py_compile.PyCompileError as e:
                print(f"  [-] {name} script has syntax error: {e}")
                return False
            finally:
                os.unlink(fname)

        # Test CLI argparse for cs-serve
        from csproxy.cli import main_serve
        result = main_serve(['--help'])
        # argparse --help returns SystemExit(0)
        print("  [+] cs-serve --help dispatches correctly")

        return True

    except SystemExit as e:
        if e.code == 0:
            print("  [+] cs-serve --help dispatches correctly")
            return True
        print(f"  [-] Unexpected SystemExit: {e.code}")
        return False

    except Exception as e:
        print(f"  [-] Serve module test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_wireguard_module():
    """Test cs-wg module imports and structure."""
    print("\n[*] Testing wireguard module (cs-wg.sh conversion)...")

    try:
        from csproxy.wireguard import (
            COMMANDS,
            WG_INTERFACE,
            WG_PORT,
            WG_LOCAL_IP,
            WG_REMOTE_IP,
            WG_NETWORK,
            TCP_RELAY_PORT,
            _REMOTE_SETUP_SCRIPT,
            show_help,
        )
        print("  [+] wireguard.py imported")

        # Verify all commands are registered
        expected = {'up', 'down', 'status', 'route', 'monitor'}
        registered = set(COMMANDS.keys())
        missing = expected - registered
        if missing:
            print(f"  [-] Missing wg commands: {missing}")
            return False
        print(f"  [+] All {len(registered)} wg commands registered")

        # Verify defaults
        assert WG_PORT == 51820, f"Expected 51820, got {WG_PORT}"
        assert TCP_RELAY_PORT == 51821
        assert WG_INTERFACE == 'cswg0'
        assert WG_LOCAL_IP == '10.99.99.2/24'
        assert WG_REMOTE_IP == '10.99.99.1/24'
        assert WG_NETWORK == '10.99.99.0/24'
        print(f"  [+] WG defaults: interface={WG_INTERFACE}, port={WG_PORT}")

        # Verify remote setup script is valid Bash (check for shebang and key markers)
        assert '#!/usr/bin/env bash' in _REMOTE_SETUP_SCRIPT
        assert 'wg-quick up wg0' in _REMOTE_SETUP_SCRIPT
        assert '{remote_private_key}' in _REMOTE_SETUP_SCRIPT
        assert '{local_public_key}' in _REMOTE_SETUP_SCRIPT
        print("  [+] Remote setup script template is valid")

        # Verify script renders without error when format() is called with test values
        rendered = _REMOTE_SETUP_SCRIPT.format(
            remote_private_key='TEST_PRIV_KEY=',
            wg_remote_ip='10.99.99.1/24',
            wg_port=51820,
            wg_network='10.99.99.0/24',
            local_public_key='TEST_PUB_KEY=',
            local_ip_host='10.99.99.2',
            remote_ip_host='10.99.99.1',
        )
        assert 'TEST_PRIV_KEY=' in rendered
        assert 'TEST_PUB_KEY=' in rendered
        assert '#!/usr/bin/env bash' in rendered
        print("  [+] Remote setup script renders correctly")

        return True

    except Exception as e:
        print(f"  [-] Wireguard module test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tools_module():
    """Test cs-tools module imports and structure."""
    print("\n[*] Testing tools module (tools-wrapper.sh conversion)...")

    try:
        from csproxy.tools import (
            TOOL_COMMANDS,
            SECLISTS,
            WORDLIST_COMMON,
            check_proxy,
            pcurl,
            pwget,
            pnmap,
            pnuclei,
            pffuf,
            phttpx,
            psqlmap,
            pcs,
            ipcheck,
            psub,
            pportscan,
            main_tools,
            show_help,
        )
        print("  [+] tools.py imported")

        # Verify all wrapped tools are present
        expected_tools = {'pcurl', 'pwget', 'pnmap', 'pnuclei', 'pffuf',
                          'phttpx', 'psqlmap', 'pcs'}
        registered = set(TOOL_COMMANDS.keys())
        missing = expected_tools - registered
        if missing:
            print(f"  [-] Missing tool wrappers: {missing}")
            return False
        print(f"  [+] All {len(registered)} tool wrappers registered")

        # Verify wordlist paths are Path objects
        from pathlib import Path
        assert isinstance(SECLISTS, Path)
        assert isinstance(WORDLIST_COMMON, Path)
        print(f"  [+] SECLISTS path: {SECLISTS}")

        # Test help dispatch
        result = main_tools(['help'])
        assert result == 0
        print("  [+] cs-tools help dispatches correctly")

        return True

    except Exception as e:
        print(f"  [-] Tools module test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 70)
    print("cs-proxy Full Installation Test (Phase 1 + Phase 2 + Phase 3)")
    print("=" * 70)

    tests = [
        test_imports,
        test_logging,
        test_config,
        test_github_manager,
        test_dependencies,
        test_exceptions,
        test_proxy_module,
        test_serve_module,
        test_wireguard_module,
        test_tools_module,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"\n[-] Test failed with exception: {e}")
            results.append(False)

    # Summary
    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"[+] ALL TESTS PASSED ({passed}/{total})")
        print("\nFull installation (Phase 1 + Phase 2 + Phase 3) is working correctly!")
        print("\nNext steps:")
        print("  - Run: cs-proxy help")
        print("  - Run: cs-proxy env")
        print("  - Run: cs-proxy status")
        print("  - Authenticate GitHub: gh auth login")
        print("  - Start proxy: cs-proxy start")
        return 0
    else:
        print(f"[-] SOME TESTS FAILED ({passed}/{total} passed)")
        print("\nPlease check the errors above and ensure:")
        print("  - Python 3.8+ is installed")
        print("  - Dependencies are installed: pip install -e .")
        return 1


if __name__ == '__main__':
    sys.exit(main())
