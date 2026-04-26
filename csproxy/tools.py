#!/usr/bin/env python3
"""
cs-proxy-tools - Proxied wrappers for common security tools.

Provides Python functions that run security tools with SOCKS5 proxy
arguments automatically applied.

Can be used as a Python library:
    from csproxy.tools import pcurl, pnmap, ipcheck

Or via the CLI:
    cs-tools ipcheck
    cs-tools pcurl https://target.com
    cs-tools pnmap -p 80,443 target.com
"""

import os
import random
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from .state import State
from .utils import Config, get_logger

VERSION = "1.0.0"


def _get_proxy_port(config: Config) -> int:
    """
    Return a random healthy tunnel port from state.json, or fall back
    to config.socks_port if no healthy tunnels are tracked.
    """
    try:
        state = State(config.config_dir)
        healthy = state.get_tunnels(kind="ssh", status="healthy")
        if healthy:
            return random.choice(healthy)["port"]
    except Exception:
        pass
    return config.socks_port


# Default wordlist paths (SecLists)
SECLISTS = Path(os.environ.get('SECLISTS', Path.home() / 'wordlists' / 'SecLists'))
WORDLIST_COMMON = SECLISTS / 'Discovery/Web-Content/common.txt'
WORDLIST_BIG = SECLISTS / 'Discovery/Web-Content/big.txt'
WORDLIST_DIRS = SECLISTS / 'Discovery/Web-Content/directory-list-2.3-medium.txt'
WORDLIST_PARAMS = SECLISTS / 'Discovery/Web-Content/burp-parameter-names.txt'
WORDLIST_SUBDOMAINS = SECLISTS / 'Discovery/DNS/subdomains-top1million-5000.txt'


# =============================================================================
# Proxy health check
# =============================================================================


def check_proxy(host: str = '127.0.0.1', port: Optional[int] = None) -> bool:
    """
    Verify the SOCKS5 proxy is running and reachable.

    Equivalent to _check_proxy() in tools-wrapper.sh.

    Returns:
        True if proxy is up, False otherwise.
    """
    config = Config()
    port = port or _get_proxy_port(config)
    result = subprocess.run(
        ['curl', '-s', '--connect-timeout', '2',
         '--socks5-hostname', f'{host}:{port}', 'https://ifconfig.me'],
        capture_output=True
    )
    if result.returncode != 0:
        print(f"[!] Warning: cs-proxy doesn't appear to be running on port {port}")
        print(f"    Start with: cs-proxy start")
        return False
    return True


# =============================================================================
# Proxied tool wrappers
# Equivalent to: pcurl, pwget, pnmap, etc. in tools-wrapper.sh
# =============================================================================


def pcurl(args: List[str], host: str = '127.0.0.1', port: Optional[int] = None) -> int:
    """
    Run curl with SOCKS5 proxy.

    Equivalent to pcurl() in tools-wrapper.sh.

    Args:
        args: curl arguments (URL and options)
        host: Proxy host (default: 127.0.0.1)
        port: Proxy port (default: config.socks_port)

    Returns:
        curl exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['curl', '--socks5-hostname', f'{host}:{port}'] + args
    ).returncode


def pwget(args: List[str], host: str = '127.0.0.1', port: Optional[int] = None) -> int:
    """
    Run wget via proxychains.

    Equivalent to pwget() in tools-wrapper.sh.

    Args:
        args: wget arguments
        host: Proxy host
        port: Proxy port

    Returns:
        wget exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    proxychains_conf = config.config_dir / 'proxychains.conf'
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['proxychains4', '-q', '-f', str(proxychains_conf), 'wget'] + args
    ).returncode


def pnmap(args: List[str], host: str = '127.0.0.1', port: Optional[int] = None) -> int:
    """
    Run nmap TCP connect scan via proxychains.

    Only TCP connect scan (-sT) works through SOCKS proxies.

    Equivalent to pnmap() in tools-wrapper.sh.

    Args:
        args: nmap arguments (target and options)
        host: Proxy host
        port: Proxy port

    Returns:
        nmap exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    proxychains_conf = config.config_dir / 'proxychains.conf'
    if not check_proxy(host, port):
        return 1
    print("[*] Note: Only TCP connect scan (-sT) works through SOCKS")
    return subprocess.run(
        ['proxychains4', '-q', '-f', str(proxychains_conf),
         'nmap', '-sT', '-Pn'] + args
    ).returncode


def pnuclei(args: List[str], host: str = '127.0.0.1', port: Optional[int] = None) -> int:
    """
    Run nuclei with SOCKS5 proxy via ALL_PROXY env var.

    Equivalent to pnuclei() in tools-wrapper.sh.

    Args:
        args: nuclei arguments
        host: Proxy host
        port: Proxy port

    Returns:
        nuclei exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    env = os.environ.copy()
    env['ALL_PROXY'] = f'socks5://{host}:{port}'
    return subprocess.run(['nuclei'] + args, env=env).returncode


def pffuf(args: List[str], host: str = '127.0.0.1', port: Optional[int] = None) -> int:
    """
    Run ffuf with SOCKS5 proxy.

    Equivalent to pffuf() in tools-wrapper.sh.

    Args:
        args: ffuf arguments
        host: Proxy host
        port: Proxy port

    Returns:
        ffuf exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['ffuf', '-x', f'socks5://{host}:{port}'] + args
    ).returncode


def phttpx(args: List[str], host: str = '127.0.0.1', port: Optional[int] = None) -> int:
    """
    Run httpx with SOCKS5 proxy.

    Equivalent to phttpx() in tools-wrapper.sh.

    Args:
        args: httpx arguments
        host: Proxy host
        port: Proxy port

    Returns:
        httpx exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['httpx', '-proxy', f'socks5://{host}:{port}'] + args
    ).returncode


def psqlmap(args: List[str], host: str = '127.0.0.1', port: Optional[int] = None) -> int:
    """
    Run sqlmap with SOCKS5 proxy.

    Equivalent to psqlmap() in tools-wrapper.sh.

    Args:
        args: sqlmap arguments
        host: Proxy host
        port: Proxy port

    Returns:
        sqlmap exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['sqlmap', f'--proxy=socks5://{host}:{port}'] + args
    ).returncode


def pcs(args: List[str], host: str = '127.0.0.1', port: Optional[int] = None) -> int:
    """
    Run any command via proxychains (generic wrapper).

    Equivalent to pcs() in tools-wrapper.sh.

    Args:
        args: Command and its arguments to run through proxychains
        host: Proxy host
        port: Proxy port

    Returns:
        Command exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    proxychains_conf = config.config_dir / 'proxychains.conf'
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['proxychains4', '-q', '-f', str(proxychains_conf)] + args
    ).returncode


# =============================================================================
# IP check utility
# =============================================================================


def ipcheck(host: str = '127.0.0.1', port: Optional[int] = None) -> None:
    """
    Compare direct IP vs proxied IP.

    Equivalent to ipcheck() in tools-wrapper.sh.
    """
    config = Config()
    port = port or _get_proxy_port(config)

    # Direct IP
    result = subprocess.run(
        ['curl', '-s', '--connect-timeout', '5', 'https://ifconfig.me'],
        capture_output=True, text=True
    )
    direct_ip = result.stdout.strip() if result.returncode == 0 else 'timeout'

    # Proxied IP
    result = subprocess.run(
        ['curl', '-s', '--connect-timeout', '5',
         '--socks5-hostname', f'{host}:{port}', 'https://ifconfig.me'],
        capture_output=True, text=True
    )
    proxied_ip = result.stdout.strip() if result.returncode == 0 else 'not connected'

    print(f"Direct IP:  {direct_ip}")
    print(f"Proxied IP: {proxied_ip}")


# =============================================================================
# Quick recon helpers
# =============================================================================


def psub(domain: str, host: str = '127.0.0.1', port: Optional[int] = None) -> int:
    """
    Quick subdomain enumeration through proxy.

    Requires subfinder + httpx. Uses phttpx() to verify live hosts.

    Equivalent to psub() in tools-wrapper.sh.

    Args:
        domain: Target domain (e.g. example.com)
        host: Proxy host
        port: Proxy port

    Returns:
        Exit code
    """
    import shutil
    config = Config()
    port = port or _get_proxy_port(config)

    if not domain:
        print("Usage: psub domain.com")
        return 1
    if not check_proxy(host, port):
        return 1

    print(f"[*] Enumerating subdomains for: {domain}")

    if not shutil.which('subfinder'):
        print("[!] subfinder not installed")
        return 1

    subfinder = subprocess.Popen(
        ['subfinder', '-d', domain, '-silent'],
        stdout=subprocess.PIPE
    )
    proxychains_conf = config.config_dir / 'proxychains.conf'
    result = subprocess.run(
        ['httpx', '-proxy', f'socks5://{host}:{port}', '-silent'],
        stdin=subfinder.stdout
    )
    subfinder.wait()
    return result.returncode


def pportscan(target: str, ports: str = '21,22,23,25,80,443,445,3306,3389,8080,8443',
              host: str = '127.0.0.1', port: Optional[int] = None) -> int:
    """
    Quick port scan through proxy.

    Equivalent to pportscan() in tools-wrapper.sh.

    Args:
        target: Target host/IP
        ports: Comma-separated port list (default: common ports)
        host: Proxy host
        port: Proxy port

    Returns:
        Exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)

    if not target:
        print("Usage: pportscan target [ports]")
        return 1

    print(f"[*] Scanning {target} ports: {ports}")
    return pnmap(['-p', ports, target], host=host, port=port)


# =============================================================================
# Help
# =============================================================================


def show_help() -> None:
    """
    Display cs-tools help text.

    Equivalent to proxy-tools-help() in tools-wrapper.sh.
    """
    print(f"""cs-proxy Tools Wrapper v{VERSION} (Python) - Proxied Security Tool Wrappers

USAGE:
    cs-tools <tool> [args...]

PROXIED TOOLS:
    pcurl       curl with SOCKS5
    pwget       wget via proxychains
    pnmap       nmap TCP connect scan
    pnuclei     nuclei with proxy
    pffuf       ffuf with proxy
    phttpx      httpx with proxy
    psqlmap     sqlmap with proxy
    pcs         generic proxychains wrapper

UTILITIES:
    ipcheck     compare direct vs proxied IP

RECON HELPERS:
    psub        subdomain enumeration (requires subfinder)
    pportscan   quick port scan

WORDLISTS:
    SecLists:   {SECLISTS}
    Common:     {WORDLIST_COMMON}
    Big:        {WORDLIST_BIG}

EXAMPLES:
    cs-tools pcurl https://target.com
    cs-tools pnmap -p 80,443 target.com
    cs-tools pffuf -u https://target.com/FUZZ -w wordlist.txt
    cs-tools ipcheck
""")


# =============================================================================
# CLI dispatch
# =============================================================================


TOOL_COMMANDS = {
    'pcurl':     ('pcurl', pcurl),
    'pwget':     ('pwget', pwget),
    'pnmap':     ('pnmap', pnmap),
    'pnuclei':   ('pnuclei', pnuclei),
    'pffuf':     ('pffuf', pffuf),
    'phttpx':    ('phttpx', phttpx),
    'psqlmap':   ('psqlmap', psqlmap),
    'pcs':       ('pcs', pcs),
}


def main_tools(argv=None):
    """
    Entry point for cs-tools command.

    Dispatches to proxied security tool wrappers.
    """
    logger = get_logger()

    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ('help', '--help', '-h'):
        show_help()
        return 0

    tool = argv[0]
    tool_args = argv[1:]

    # Single-arg commands
    if tool == 'ipcheck':
        ipcheck()
        return 0

    if tool == 'psub':
        if not tool_args:
            print("Usage: cs-tools psub domain.com")
            return 1
        return psub(tool_args[0])

    if tool == 'pportscan':
        if not tool_args:
            print("Usage: cs-tools pportscan target [ports]")
            return 1
        ports = tool_args[1] if len(tool_args) > 1 else '21,22,23,25,80,443,445,3306,3389,8080,8443'
        return pportscan(tool_args[0], ports)

    if tool in TOOL_COMMANDS:
        _, fn = TOOL_COMMANDS[tool]
        return fn(tool_args)

    logger.error(f"Unknown tool: {tool}. Run 'cs-tools help' for usage.")
    return 1


if __name__ == '__main__':
    sys.exit(main_tools())
