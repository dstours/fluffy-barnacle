#!/usr/bin/env python3
"""
cs-proxy - SOCKS5/HTTP proxy management via GitHub Codespaces.

Converts GitHub Codespaces into SOCKS5 and HTTP proxies by establishing
SSH tunnels. Provides automatic Codespace selection, reconnect logic, and
integration with common security tools.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from .github import GitHubManager
from .utils import (
    Config,
    GitHubAuthError,
    ProxyError,
    SSHTunnelError,
    check_dependencies,
    get_logger,
)

# Re-export classes from extracted modules for backward compatibility
from .tunnel import SSHTunnel, HTTPProxyManager  # noqa: F401
from .codespace import CodespaceSelector  # noqa: F401
from .display import (  # noqa: F401
    print_env_exports, print_usage_examples, print_burp_config,
    show_status, show_logs, show_help,
)

VERSION = "1.0.0"


# =============================================================================
# Configuration Utilities
# =============================================================================


class ProxychainsConfig:
    """Generate proxychains configuration files."""

    @staticmethod
    def generate(config: Config) -> None:
        """Generate proxychains.conf file."""
        logger = get_logger()
        conf_file = config.config_dir / 'proxychains.conf'

        content = f"""# Proxychains configuration for cs-proxy
# Generated on {time.strftime('%Y-%m-%d %H:%M:%S')}

# Quiet mode (no output)
quiet_mode

# Proxy DNS requests through the proxy
proxy_dns

# Timeouts
tcp_read_time_out 15000
tcp_connect_time_out 8000

# ProxyList
[ProxyList]
socks5 127.0.0.1 {config.socks_port}
"""
        conf_file.write_text(content)
        conf_file.chmod(0o600)
        logger.info(f"Proxychains config generated: {conf_file}")

        print(f"\nUsage:")
        print(f"  proxychains4 -f {conf_file} <command>")
        print(f"  # or add alias:")
        print(f"  alias pcs='proxychains4 -f {conf_file}'")


# =============================================================================
# SSH Key Management
# =============================================================================


def generate_ssh_key(config: Config) -> None:
    """Generate SSH keypair for Codespace access."""
    logger = get_logger()
    key_file = config.config_dir / 'codespace_key'

    if key_file.exists():
        logger.warning(f"SSH key already exists at {key_file}")
        answer = input("Regenerate? [y/N] ").strip().lower()
        if answer != 'y':
            return

    logger.info("Generating SSH key for Codespace access...")

    datestamp = time.strftime('%Y%m%d')
    result = subprocess.run(
        [
            'ssh-keygen', '-t', 'ed25519',
            '-f', str(key_file),
            '-N', '',
            '-C', f'cs-proxy-{datestamp}'
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"ssh-keygen failed: {result.stderr}")

    key_file.chmod(0o600)
    pub_key_file = key_file.with_suffix('.pub')
    if pub_key_file.exists():
        pub_key_file.chmod(0o644)

    logger.info("SSH key generated successfully")
    print("\nAdd this public key to your GitHub account:")
    print("Settings -> SSH and GPG keys -> New SSH key\n")
    print(pub_key_file.read_text())


# =============================================================================
# GitHub Token Management
# =============================================================================


def set_github_token(token: str, config: Config, gh: GitHubManager) -> None:
    """Validate and save a GitHub Personal Access Token."""
    logger = get_logger()

    if not token:
        print("Enter your GitHub Personal Access Token:")
        print("(Create one at https://github.com/settings/tokens/new with 'codespace' scope)")
        token = input("> ").strip()

    if not token:
        raise ValueError("No token provided")

    if not (token.startswith('ghp_') or token.startswith('ghs_')):
        logger.warning("Token doesn't match expected format (ghp_* or ghs_*)")
        answer = input("Continue anyway? [y/N] ").strip().lower()
        if answer != 'y':
            raise ValueError("Aborted")

    logger.info("Validating token...")
    os.environ['GH_TOKEN'] = token

    result = subprocess.run(['gh', 'auth', 'status'], capture_output=True)
    if result.returncode != 0:
        raise GitHubAuthError("Token validation failed. Check scopes: codespace, repo")

    gh.save_token(token)
    logger.info("Token validated and saved successfully")


# =============================================================================
# Split Tunneling
# =============================================================================


def setup_split_tunnel(config: Config) -> None:
    """Interactively set up split tunneling for specific targets."""
    logger = get_logger()
    target_file = config.config_dir / 'targets.txt'

    print("Split tunneling routes specific targets through the proxy.")
    print("Enter target domains/IPs (one per line, empty line to finish):\n")

    targets = []
    while True:
        target = input("> ").strip()
        if not target:
            break
        targets.append(target)

    if not targets:
        logger.warning("No targets specified")
        return

    target_file.write_text('\n'.join(targets) + '\n')
    logger.info(f"Targets saved to {target_file}")

    print(f"""
For iptables-based routing, you need to:

1. Install redsocks: sudo apt install redsocks
2. Configure redsocks to use the SOCKS proxy
3. Use iptables to redirect specific traffic to redsocks

Example redsocks config:
  base {{ log_debug = off; log_info = off; daemon = on; redirector = iptables; }}
  redsocks {{ local_ip = 127.0.0.1; local_port = 12345;
             ip = 127.0.0.1; port = {config.socks_port}; type = socks5; }}

Example iptables rule (for a specific destination):
  iptables -t nat -A OUTPUT -p tcp -d <TARGET_IP> -j REDIRECT --to-ports 12345
""")


# =============================================================================
# Helper
# =============================================================================


def _get_codespace(config: Config, gh: GitHubManager) -> str:
    """Get current Codespace name, selecting if needed."""
    if config.codespace_name:
        return config.codespace_name

    selector = CodespaceSelector(gh, config)
    name = selector.select()
    config.set('codespace_name', name)
    return name


def _ensure_codespaces(config: Config, gh: GitHubManager, count: int) -> list:
    """Ensure at least `count` codespaces exist, creating if needed."""
    logger = get_logger()
    existing = gh.list_codespaces()
    names = [cs['name'] for cs in existing[:count]]

    for name in names:
        logger.info(f"Using existing codespace: {name}")

    locations = config.locations
    while len(names) < count:
        idx = len(names)
        location = locations[idx] if idx < len(locations) else (locations[0] if locations else '')
        logger.info(f"Creating codespace {idx+1}/{count}"
                    + (f" in {location}" if location else "") + "...")
        selector = CodespaceSelector(gh, config)
        name = selector._create_and_wait(CodespaceSelector.BLANK_REPO, location=location)
        names.append(name)

    return names


def cmd_start(args, config: Config, gh: GitHubManager) -> int:
    """Start SOCKS5 proxy tunnel."""
    logger = get_logger()
    check_dependencies(['gh', 'ssh', 'curl'])
    gh.check_auth()

    num_proxies = min(config.get('num_proxies', 1), 2)
    selector = CodespaceSelector(gh, config)

    if num_proxies > 1:
        names = _ensure_codespaces(config, gh, num_proxies)
        codespace = names[0]
        config.set('codespace_name', codespace)
        config.set('codespace_names', names)
        logger.info(f"Using {len(names)} codespace(s)")
        for i, name in enumerate(names):
            port = config.socks_port + i
            logger.info(f"  {name}  →  socks5://127.0.0.1:{port}")
    else:
        tracked = list(config.codespace_names)

        if not tracked:
            # First start: select or create a codespace
            codespace = _get_codespace(config, gh)
            tracked = [codespace]
            config.set('codespace_name', codespace)
            config.set('codespace_names', tracked)
        else:
            # Check if all tracked codespaces already have running tunnels
            all_running = all(
                SSHTunnel(config, n, port=config.socks_port + i,
                          pid_suffix=('' if i == 0 else str(i + 1))).is_running()
                for i, n in enumerate(tracked)
            )
            if all_running:
                # All running: add another codespace and tunnel
                logger.info("All managed Codespaces already have tunnels. Adding a new one...")
                new_name = selector._create_interactively()
                tracked.append(new_name)
                config.set('codespace_names', tracked)
            config.set('codespace_name', tracked[0])

    # Start tunnels for any tracked codespace that isn't already running
    for i, name in enumerate(config.codespace_names):
        suffix = '' if i == 0 else str(i + 1)
        port = config.socks_port + i
        t = SSHTunnel(config, name, port=port, pid_suffix=suffix)
        if not t.is_running():
            selector.ensure_running(name)
            t.start(start_timeout=30 if i == 0 else 90)

    ProxychainsConfig.generate(config)
    print_usage_examples(config)

    config.save()
    return 0


def cmd_stop(args, config: Config, gh: GitHubManager) -> int:
    """Stop proxy tunnel."""
    tunnel = SSHTunnel(config, config.codespace_name or '')
    tunnel.stop()

    # Stop tunnels for any additional codespaces
    for i in range(1, len(config.codespace_names)):
        SSHTunnel(config, '', port=config.socks_port + i, pid_suffix=str(i + 1)).stop()

    http = HTTPProxyManager(config)
    http.stop()
    return 0


def cmd_restart(args, config: Config, gh: GitHubManager) -> int:
    """Restart proxy."""
    cmd_stop(args, config, gh)
    time.sleep(2)
    return cmd_start(args, config, gh)


def cmd_status(args, config: Config, gh: GitHubManager) -> int:
    """Show proxy status."""
    show_status(config, gh)
    return 0


def cmd_list(args, config: Config, gh: GitHubManager) -> int:
    """List Codespaces."""
    check_dependencies(['gh'])
    gh.check_auth()

    get_logger().info("Fetching available Codespaces...")
    print()

    codespaces = gh.list_codespaces()
    if not codespaces:
        print("No Codespaces found.")
        return 0

    header = f"{'NAME':<40} {'STATE':<15} {'REPOSITORY':<35} {'CREATED'}"
    print(header)
    print('-' * len(header))
    for cs in codespaces:
        name = cs.get('name', '')[:38]
        state = cs.get('state', '')[:13]
        repo = cs.get('repository', '')[:33]
        created = cs.get('createdAt', '')[:10]
        print(f"{name:<40} {state:<15} {repo:<35} {created}")
    print()
    return 0


def cmd_create(args, config: Config, gh: GitHubManager) -> int:
    """Create a new Codespace and add it to the tracked list."""
    check_dependencies(['gh'])
    gh.check_auth()

    selector = CodespaceSelector(gh, config)
    name = selector._create_interactively()

    names = list(config.codespace_names)
    if name not in names:
        names.append(name)
    config.set('codespace_names', names)
    config.set('codespace_name', name)
    config.save()
    return 0


def cmd_set(args, config: Config, gh: GitHubManager) -> int:
    """Set the active Codespace by name."""
    logger = get_logger()

    codespace_name = args[0] if args else None
    if not codespace_name:
        logger.error("Usage: cs-proxy set <codespace-name>")
        return 1

    config.set('codespace_name', codespace_name)
    config.save()
    logger.info(f"Codespace set to: {codespace_name}")
    return 0


def cmd_http(args, config: Config, gh: GitHubManager) -> int:
    """Start HTTP proxy."""
    http = HTTPProxyManager(config)
    http.start()
    return 0


def cmd_proxychains(args, config: Config, gh: GitHubManager) -> int:
    """Generate proxychains configuration."""
    ProxychainsConfig.generate(config)
    return 0


def cmd_env(args, config: Config, gh: GitHubManager) -> int:
    """Print environment variable exports."""
    print_env_exports(config)
    return 0


def cmd_burp(args, config: Config, gh: GitHubManager) -> int:
    """Print Burp Suite configuration."""
    print_burp_config(config)
    return 0


def cmd_keygen(args, config: Config, gh: GitHubManager) -> int:
    """Generate SSH key for Codespace access."""
    generate_ssh_key(config)
    return 0


def cmd_config(args, config: Config, gh: GitHubManager) -> int:
    """Open config file in editor."""
    editor = os.environ.get('EDITOR', 'nano')
    os.execvp(editor, [editor, str(config.config_file)])
    return 0


def cmd_logs(args, config: Config, gh: GitHubManager) -> int:
    """Show proxy logs."""
    lines = int(args[0]) if args else 50
    show_logs(config, lines)
    return 0


def cmd_split(args, config: Config, gh: GitHubManager) -> int:
    """Set up split tunneling."""
    setup_split_tunnel(config)
    return 0


def _pick_codespace(args, config: Config, gh: GitHubManager) -> str:
    """
    Resolve which codespace to target from args or interactive menu.

    Resolution order:
      1. args[0] is a digit  → index into codespace_names
      2. args[0] is a string → use directly as codespace name
      3. Multiple managed codespaces → show numbered menu
      4. Fallback                    → _get_codespace (active / selector)
    """
    names = config.codespace_names

    if args:
        arg = args[0]
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(names):
                return names[idx]
            raise ValueError(f"No codespace at index {arg}. "
                             f"Tracked: {len(names)} ({', '.join(names)})")
        return arg  # treat as explicit name

    if len(names) > 1:
        print("\nSelect Codespace:")
        for i, name in enumerate(names, 1):
            idx = names.index(name)
            role = f" [:{config.socks_port + idx}]"
            print(f"  {i}) {name}{role}")
        choice = input("> ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                return names[idx]
        print("Invalid selection, using active codespace")

    return _get_codespace(config, gh)


def cmd_ssh(args, config: Config, gh: GitHubManager) -> int:
    """Open interactive SSH session in Codespace."""
    check_dependencies(['gh', 'ssh'])
    gh.check_auth()

    codespace = _pick_codespace(args, config, gh)
    selector = CodespaceSelector(gh, config)
    selector.ensure_running(codespace)

    get_logger().info(f"Connecting to {codespace}...")
    os.execvp('gh', ['gh', 'codespace', 'ssh', '--codespace', codespace])
    return 0


def cmd_run(args, config: Config, gh: GitHubManager) -> int:
    """Run a command in the Codespace."""
    check_dependencies(['gh', 'ssh'])
    gh.check_auth()

    if not args:
        get_logger().error("Usage: cs-proxy run <command>")
        return 1

    codespace = _get_codespace(config, gh)
    selector = CodespaceSelector(gh, config)
    selector.ensure_running(codespace)

    result = subprocess.run(
        ['gh', 'codespace', 'ssh', '--codespace', codespace, '--'] + args
    )
    return result.returncode


def cmd_name(args, config: Config, gh: GitHubManager) -> int:
    """Print current Codespace name."""
    check_dependencies(['gh'])
    gh.check_auth()

    codespace = _get_codespace(config, gh)
    print(codespace)
    return 0


def cmd_teardown(args, config: Config, gh: GitHubManager) -> int:
    """Stop proxy and all managed Codespaces (saves compute, keeps storage)."""
    logger = get_logger()
    check_dependencies(['gh'])
    gh.check_auth()

    tunnel = SSHTunnel(config, config.codespace_name or '')
    tunnel.stop()

    all_names = config.codespace_names or ([config.codespace_name] if config.codespace_name else [])
    if all_names:
        for name in all_names:
            logger.info(f"Stopping Codespace: {name}")
            gh.run_gh_command(
                ['codespace', 'stop', '--codespace', name], check=False
            )
        logger.info(f"Stopped {len(all_names)} codespace(s) (still exist, no compute billing)")
    else:
        logger.warning("No Codespace configured. Use: gh codespace stop -c <name>")

    return 0


def cmd_delete(args, config: Config, gh: GitHubManager) -> int:
    """Delete Codespace(s) permanently."""
    logger = get_logger()
    check_dependencies(['gh'])
    gh.check_auth()

    # List all codespaces to let user choose
    codespaces = gh.list_codespaces()
    if not codespaces:
        logger.info("No codespaces found")
        return 0

    names = [cs['name'] for cs in codespaces]

    if len(names) > 1:
        print(f"\nYou have {len(names)} codespaces:")
        for i, name in enumerate(names, 1):
            print(f"  {i}) {name}")
        print()
        print("Options:")
        print("  a) Delete ALL")
        for i, name in enumerate(names, 1):
            print(f"  {i}) Delete only {name}")
        print("  n) Cancel")
        print()
        choice = input("Choice: ").strip().lower()

        if choice == 'a':
            to_delete = names
        elif choice.isdigit() and 1 <= int(choice) <= len(names):
            to_delete = [names[int(choice) - 1]]
        else:
            logger.info("Cancelled")
            return 0
    else:
        to_delete = names
        print(f"\nThis will PERMANENTLY delete: {to_delete[0]}")
        confirm = input("Are you sure? [y/N] ").strip().lower()
        if confirm != 'y':
            logger.info("Cancelled")
            return 0

    # Stop tunnel if active codespace is being deleted
    for name in to_delete:
        SSHTunnel(config, name).stop()

    # Delete codespaces
    for name in to_delete:
        gh.delete_codespace(name, force=True)

    remaining = [n for n in config.codespace_names if n not in to_delete]
    config.set('codespace_name', remaining[0] if remaining else '')
    config.set('codespace_names', remaining)
    config.save()
    return 0


def cmd_token(args, config: Config, gh: GitHubManager) -> int:
    """Set GitHub token."""
    config.ensure_dirs()
    token = args[0] if args else ''
    set_github_token(token, config, gh)
    return 0


def cmd_aliases(args, config: Config, gh: GitHubManager) -> int:
    """Write shell aliases to ~/.bashrc and/or ~/.zshrc."""
    logger = get_logger()
    home = Path.home()

    proxychains_conf = '${CS_PROXY_CONFIG_DIR:-$HOME/.config/cs-proxy}/proxychains.conf'
    alias_block = f"""\n# cs-proxy aliases
alias proxy-start='cs-proxy start'
alias proxy-stop='cs-proxy stop'
alias proxy-status='cs-proxy status'
alias pcs='proxychains4 -f {proxychains_conf}'
alias cs-wg='sudo env "PATH=$PATH" cs-wg'
"""

    rc_files = [f for f in [home / '.bashrc', home / '.zshrc'] if f.exists()]
    if not rc_files:
        rc_files = [home / '.bashrc']

    wrote = []
    for rc in rc_files:
        existing = rc.read_text() if rc.exists() else ''
        if 'cs-proxy aliases' in existing:
            logger.info(f"Aliases already present in {rc}")
            continue
        with rc.open('a') as f:
            f.write(alias_block)
        wrote.append(rc)
        logger.info(f"Added aliases to {rc}")

    if wrote:
        print("\nSource your shell to activate:")
        for rc in wrote:
            print(f"  source {rc}")
    return 0


def cmd_help(args, config: Config, gh: GitHubManager) -> int:
    """Show help."""
    show_help()
    return 0


# =============================================================================
# Command Dispatch Table
# =============================================================================


COMMANDS = {
    'start':        cmd_start,
    'stop':         cmd_stop,
    'restart':      cmd_restart,
    'status':       cmd_status,
    'list':         cmd_list,
    'create':       cmd_create,
    'set':          cmd_set,
    'http':         cmd_http,
    'proxychains':  cmd_proxychains,
    'env':          cmd_env,
    'burp':         cmd_burp,
    'keygen':       cmd_keygen,
    'config':       cmd_config,
    'logs':         cmd_logs,
    'split':        cmd_split,
    'ssh':          cmd_ssh,
    'run':          cmd_run,
    'name':         cmd_name,
    'teardown':     cmd_teardown,
    'down':         cmd_teardown,   # Alias
    'delete':       cmd_delete,
    'rm':           cmd_delete,     # Alias
    'token':        cmd_token,
    'aliases':      cmd_aliases,
    'help':         cmd_help,
}
