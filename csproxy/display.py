#!/usr/bin/env python3
"""
Display and status functions for cs-proxy.

Pure output functions that read config and print formatted information.
Extracted from proxy.py for modularity.
"""

import os
import subprocess
from typing import Optional

from .utils import Config, get_logger


VERSION = "1.0.0"


def print_env_exports(config: Config) -> None:
    """Print shell environment variable exports for proxy-aware applications."""
    print(f"""
# Add these to your shell for proxy-aware applications:

# SOCKS5 Proxy
export ALL_PROXY="socks5://127.0.0.1:{config.socks_port}"
export all_proxy="socks5://127.0.0.1:{config.socks_port}"

# HTTP Proxy (if HTTP proxy running)
export HTTP_PROXY="http://127.0.0.1:{config.http_proxy_port}"
export HTTPS_PROXY="http://127.0.0.1:{config.http_proxy_port}"
export http_proxy="http://127.0.0.1:{config.http_proxy_port}"
export https_proxy="http://127.0.0.1:{config.http_proxy_port}"

# No proxy for local addresses
export NO_PROXY="localhost,127.0.0.1,::1"
export no_proxy="localhost,127.0.0.1,::1"
""")


def print_usage_examples(config: Config) -> None:
    """Print usage examples for the proxy."""
    proxychains_conf = config.config_dir / 'proxychains.conf'
    print(f"""
=== Usage Examples ===

# Check your proxied IP
curl --socks5-hostname 127.0.0.1:{config.socks_port} https://ifconfig.me

# proxychains (wget, nmap, etc.)
proxychains4 -f {proxychains_conf} wget https://example.com
proxychains4 -f {proxychains_conf} nmap -sT -Pn target.com

# Firefox: Set network.proxy.socks to 127.0.0.1:{config.socks_port}
# Burp Suite: User Options -> SOCKS Proxy -> 127.0.0.1:{config.socks_port}
""")


def print_burp_config(config: Config) -> None:
    """Print Burp Suite configuration instructions."""
    print(f"""
=== Burp Suite Configuration ===

To route Burp Suite traffic through the Codespace proxy:

1. Open Burp Suite
2. Go to: Settings -> Network -> Connections
3. Under "SOCKS proxy", configure:
   - Use SOCKS proxy: CHECKED
   - SOCKS proxy host: 127.0.0.1
   - SOCKS proxy port: {config.socks_port}
   - Do DNS lookups over SOCKS proxy: CHECKED

4. Test: Spider a target and verify the IP in Codespace logs

For upstream proxy chaining (Browser -> Burp -> SOCKS -> Codespace):
Your browser connects to Burp normally, and Burp routes through SOCKS.
""")


def show_status(config: Config, gh) -> None:
    """Display proxy and Codespace status information."""
    from .tunnel import SSHTunnel

    logger = get_logger()
    print("\n=== cs-proxy Status ===\n")

    pid_file = config.config_dir / 'proxy.pid'

    proxy_running = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            proxy_running = True
            print(f"Proxy Status:    RUNNING (PID: {pid})")
        except (ProcessLookupError, PermissionError, ValueError):
            print("Proxy Status:    STOPPED (stale PID file)")
    else:
        print("Proxy Status:    STOPPED")

    all_names = config.codespace_names or ([config.codespace_name] if config.codespace_name else [])
    num_tunnels = len(all_names)

    if proxy_running:
        if num_tunnels > 1:
            print(f"\nTunnels:")
            for i, name in enumerate(all_names):
                port = config.socks_port + i
                t = SSHTunnel(config, name, port=port, pid_suffix=('' if i == 0 else str(i + 1)))
                healthy = t.health_check()
                exit_ip = t.get_exit_ip() if healthy else 'unreachable'
                health_str = "HEALTHY" if healthy else "UNHEALTHY"
                print(f"  :{port}  {health_str:<10}  {exit_ip or 'unknown':<16}  {name}")
        else:
            tunnel = SSHTunnel(config, config.codespace_name)
            if tunnel.health_check():
                exit_ip = tunnel.get_exit_ip()
                print(f"Proxy Health:    HEALTHY")
                print(f"Proxied IP:      {exit_ip or 'unknown'}")
            else:
                print(f"Proxy Health:    UNHEALTHY")

    print(f"SOCKS5 Port:     {config.socks_port}")
    print(f"HTTP Port:       {config.http_proxy_port}")

    # Show all codespaces
    import json
    result = gh.run_gh_command(
        ['codespace', 'list', '--json', 'name,state,location'], check=False
    )
    codespaces = []
    try:
        codespaces = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        pass

    active = config.codespace_name
    managed = set(config.codespace_names)
    if codespaces:
        print(f"\nCodespaces:")
        for cs in codespaces:
            name = cs.get('name', '')
            state = cs.get('state', 'unknown')
            location = cs.get('location', '')
            if name in managed:
                idx = config.codespace_names.index(name) if name in config.codespace_names else -1
                role = f" [tunnel :{config.socks_port + idx}]" if idx >= 0 else " [managed]"
            else:
                role = ""
            loc_str = f"  {location}" if location else ""
            print(f"  {name:<45} {state:<12}{loc_str}{role}")
    elif active:
        print(f"\nCodespace:       {active}")

    result = subprocess.run(
        ['curl', '-s', '--connect-timeout', '5', 'https://ifconfig.me'],
        capture_output=True,
        text=True,
        timeout=10
    )
    local_ip = result.stdout.strip() if result.returncode == 0 else 'unknown'
    print(f"\nYour Direct IP:  {local_ip}")
    print()


def show_logs(config: Config, lines: int = 50) -> None:
    """Show recent proxy log entries."""
    logger = get_logger()
    log_file = config.config_dir / 'proxy.log'

    if not log_file.exists():
        logger.warning("No log file found")
        return

    content = log_file.read_text()
    log_lines = content.splitlines()
    tail = log_lines[-lines:] if len(log_lines) > lines else log_lines
    print('\n'.join(tail))


def show_help() -> None:
    """Display help information."""
    print(f"""cs-proxy - GitHub Codespaces Proxy Tool v{VERSION} (Python)

USAGE:
    cs-proxy <command> [options]

COMMANDS:
    start           Start the SOCKS5 proxy tunnel
    stop            Stop the proxy tunnel
    restart         Restart the proxy tunnel
    status          Show proxy and Codespace status

    ssh [n|name]    Open interactive shell in Codespace (menu if multiple)
    run <cmd>       Run a command in the Codespace
    name            Print the current Codespace name

    down            Stop proxy and Codespace (saves storage, no compute)
    delete          Permanently delete the Codespace

    list            List available Codespaces
    create          Create a new Codespace
    set <n>         Set the default Codespace

    http            Start HTTP proxy (requires SOCKS running)
    proxychains     Generate proxychains configuration
    env             Show environment variable exports
    burp            Show Burp Suite configuration

    keygen          Generate SSH key for Codespace access
    config          Edit configuration
    logs [n]        Show last n lines of log (default: 50)
    token [token]   Set GitHub Personal Access Token
    aliases         Write shell aliases to ~/.bashrc / ~/.zshrc

    help            Show this help message

OPTIONS:
    -p, --port         SOCKS5 proxy port (default: 1080)
    -n, --num-proxies  Number of codespaces/tunnels to create (1-2, default: 1)
    -c, --codespace    Codespace name to use
    -l, --location     Region for new Codespace: EastUs, WestUs2, WestEurope, SouthEastAsia
                       Repeat for multiple codespaces: -l WestEurope -l EastUs
    -v, --verbose      Enable verbose output

EXAMPLES:
    # Quick start (auto-selects codespace)
    cs-proxy start

    # Create 2 codespaces with different exit IPs (ports 1080 and 1081)
    cs-proxy -n 2 start -l WestEurope -l EastUs

    # Get a shell in the codespace
    cs-proxy ssh

    # Run a command
    cs-proxy run whoami
    cs-proxy run curl ifconfig.me

    # Check your proxied IP
    curl --socks5-hostname 127.0.0.1:1080 https://ifconfig.me

FILES:
    Config:         ~/.config/cs-proxy/config.yaml
    Proxychains:    ~/.config/cs-proxy/proxychains.conf
    Log:            ~/.config/cs-proxy/proxy.log
""")
