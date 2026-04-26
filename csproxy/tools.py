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

import argparse
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .state import State
from .utils import Config, get_logger

VERSION = "1.0.0"

# Cache for proxy health checks: {(host, port): (timestamp, healthy)}
_CHECK_CACHE: Dict[Tuple[str, int], Tuple[float, bool]] = {}


# =============================================================================
# Proxy port selection
# =============================================================================


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


# =============================================================================
# Wordlist paths
# =============================================================================

SECLISTS = Path(os.environ.get('SECLISTS', Path.home() / 'wordlists' / 'SecLists'))
WORDLIST_COMMON = SECLISTS / 'Discovery/Web-Content/common.txt'
WORDLIST_BIG = SECLISTS / 'Discovery/Web-Content/big.txt'
WORDLIST_DIRS = SECLISTS / 'Discovery/Web-Content/directory-list-2.3-medium.txt'
WORDLIST_PARAMS = SECLISTS / 'Discovery/Web-Content/burp-parameter-names.txt'
WORDLIST_SUBDOMAINS = SECLISTS / 'Discovery/DNS/subdomains-top1million-5000.txt'


# =============================================================================
# Proxy health check
# =============================================================================


def check_proxy(
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    _bypass_cache: bool = False,
) -> bool:
    """
    Verify the SOCKS5 proxy is running and reachable.

    Equivalent to _check_proxy() in tools-wrapper.sh.

    Returns:
        True if proxy is up, False otherwise.
    """
    config = Config()
    port = port or _get_proxy_port(config)
    key = (host, port)

    if not _bypass_cache:
        ts, healthy = _CHECK_CACHE.get(key, (0, False))
        if time.monotonic() - ts < 5:
            if not healthy:
                print(
                    f"[!] Warning: cs-proxy doesn't appear to be running on port {port}"
                )
                print("    Start with: cs-proxy start")
            return healthy

    result = subprocess.run(
        [
            'curl', '-s', '--connect-timeout', '2',
            '--socks5-hostname', f'{host}:{port}', 'https://ifconfig.me',
        ],
        capture_output=True,
        timeout=10,
    )
    healthy = result.returncode == 0
    _CHECK_CACHE[key] = (time.monotonic(), healthy)

    if not healthy:
        print(f"[!] Warning: cs-proxy doesn't appear to be running on port {port}")
        print("    Start with: cs-proxy start")
    return healthy


# =============================================================================
# Unified proxy environment builder
# =============================================================================


def _proxy_env(host: str, port: int) -> dict:
    """
    Build environment dict with SOCKS5 proxy variables.

    Sets ALL_PROXY, HTTP_PROXY, HTTPS_PROXY, and SOCKS_PROXY so that
    tools with native proxy support pick up the tunnel automatically.
    """
    env = os.environ.copy()
    proxy_url = f'socks5h://{host}:{port}'
    env['ALL_PROXY'] = proxy_url
    env['HTTP_PROXY'] = proxy_url
    env['HTTPS_PROXY'] = proxy_url
    env['SOCKS_PROXY'] = proxy_url
    return env


# =============================================================================
# nmap argument sanitizer
# =============================================================================

# Scan types that don't work through SOCKS5 / proxychains
_NMAP_INVALID_SCANS = frozenset([
    '-sS', '-sF', '-sN', '-sX', '-sU', '-sA', '-sW', '-sM', '-sI', '-sO', '-sZ', '-sY',
])

# Options that don't work through SOCKS5 / proxychains (may have values)
_NMAP_INVALID_OPTS = frozenset([
    '-O',
    '--osscan-guess',
    '--osscan-limit',
    '--max-os-tries',
])


def _sanitize_nmap_args(args: List[str]) -> List[str]:
    """
    Strip incompatible nmap flags for SOCKS5/proxychains usage.

    Forces -sT (TCP connect) and -Pn (no ping).  Warns if running as
    root because nmap defaults to SYN scan (-sS) which bypasses the
    proxy and leaks the real IP address.

    Auto-adds --max-parallelism 10 to prevent overwhelming the proxy.
    Suggests -n when not present because DNS through proxychains is
    known to be buggy and can cause segfaults.
    """
    logger = get_logger()

    # Warn if running as root (defaults to SYN scan = IP leakage)
    try:
        if os.geteuid() == 0:
            logger.warning(
                "Running nmap as root defaults to SYN scan (-sS) which "
                "BYPASSES the SOCKS proxy and leaks your real IP. "
                "cs-tools forces -sT (TCP connect) instead."
            )
    except AttributeError:
        pass  # Windows has no geteuid

    sanitized = []
    dropped = []
    i = 0
    while i < len(args):
        arg = args[i]

        # Drop scan types that don't work through SOCKS
        if arg in _NMAP_INVALID_SCANS:
            dropped.append(arg)
            i += 1
            continue

        # Drop OS detection and related options
        if arg in _NMAP_INVALID_OPTS:
            dropped.append(arg)
            if i + 1 < len(args) and not args[i + 1].startswith('-'):
                dropped.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue

        # Drop traceroute (requires ICMP)
        if arg == '--traceroute':
            dropped.append(arg)
            i += 1
            continue

        # Drop raw scanflags manipulation
        if arg == '--scanflags':
            dropped.append(arg)
            if i + 1 < len(args) and not args[i + 1].startswith('-'):
                dropped.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue

        sanitized.append(arg)
        i += 1

    if dropped:
        logger.warning(f"Dropped incompatible nmap flags: {', '.join(dropped)}")

    # Force prepend required flags (insert in reverse so -Pn ends up first)
    for flag in reversed(('-Pn', '-sT')):
        if flag not in sanitized:
            sanitized.insert(0, flag)

    # Auto-add --max-parallelism if not present (prevents proxy overload)
    if '--max-parallelism' not in sanitized and '-T' not in ''.join(sanitized):
        sanitized.append('--max-parallelism')
        sanitized.append('10')
        logger.info("Added --max-parallelism 10 to prevent proxy overload")

    # Suggest -n if not present (DNS through proxychains can be buggy)
    if '-n' not in sanitized and '-R' not in sanitized:
        logger.info("Tip: add -n to skip DNS resolution (more reliable through proxies)")

    return sanitized


# =============================================================================
# Proxied tool wrappers
# =============================================================================


def pcurl(
    args: List[str],
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 30,
) -> int:
    """
    Run curl with SOCKS5 proxy.

    Equivalent to pcurl() in tools-wrapper.sh.

    Args:
        args: curl arguments (URL and options)
        host: Proxy host (default: 127.0.0.1)
        port: Proxy port (default: config.socks_port)
        timeout: Command timeout in seconds (default: 30)

    Returns:
        curl exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['curl', '--socks5-hostname', f'{host}:{port}'] + args,
        timeout=timeout,
    ).returncode


def pwget(
    args: List[str],
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 300,
) -> int:
    """
    Run wget via proxychains.

    Equivalent to pwget() in tools-wrapper.sh.

    Args:
        args: wget arguments
        host: Proxy host
        port: Proxy port
        timeout: Command timeout in seconds (default: 300)

    Returns:
        wget exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    proxychains_conf = config.config_dir / 'proxychains.conf'
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['proxychains4', '-q', '-f', str(proxychains_conf), 'wget'] + args,
        timeout=timeout,
    ).returncode


def pnmap(
    args: List[str],
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 600,
) -> int:
    """
    Run nmap TCP connect scan via proxychains.

    Only TCP connect scan (-sT) works through SOCKS proxies.  Incompatible
    flags such as -sS, -sU, -O, and --traceroute are automatically removed.
    --max-parallelism 10 is added if not present to avoid overloading the
    proxy.

    Equivalent to pnmap() in tools-wrapper.sh.

    Args:
        args: nmap arguments (target and options)
        host: Proxy host
        port: Proxy port
        timeout: Command timeout in seconds (default: 600)

    Returns:
        nmap exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    proxychains_conf = config.config_dir / 'proxychains.conf'
    if not check_proxy(host, port):
        return 1
    args = _sanitize_nmap_args(args)
    return subprocess.run(
        ['proxychains4', '-q', '-f', str(proxychains_conf), 'nmap'] + args,
        timeout=timeout,
    ).returncode


def pnuclei(
    args: List[str],
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 600,
) -> int:
    """
    Run nuclei with SOCKS5 proxy via ALL_PROXY env var.

    Equivalent to pnuclei() in tools-wrapper.sh.

    Args:
        args: nuclei arguments
        host: Proxy host
        port: Proxy port
        timeout: Command timeout in seconds (default: 600)

    Returns:
        nuclei exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    env = _proxy_env(host, port)
    return subprocess.run(
        ['nuclei'] + args,
        env=env,
        timeout=timeout,
    ).returncode


def pffuf(
    args: List[str],
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 600,
) -> int:
    """
    Run ffuf with SOCKS5 proxy.

    Equivalent to pffuf() in tools-wrapper.sh.

    Args:
        args: ffuf arguments
        host: Proxy host
        port: Proxy port
        timeout: Command timeout in seconds (default: 600)

    Returns:
        ffuf exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['ffuf', '-x', f'socks5://{host}:{port}'] + args,
        timeout=timeout,
    ).returncode


def phttpx(
    args: List[str],
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 300,
) -> int:
    """
    Run httpx with SOCKS5 proxy.

    Equivalent to phttpx() in tools-wrapper.sh.

    Args:
        args: httpx arguments
        host: Proxy host
        port: Proxy port
        timeout: Command timeout in seconds (default: 300)

    Returns:
        httpx exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['httpx', '-proxy', f'socks5://{host}:{port}'] + args,
        timeout=timeout,
    ).returncode


def psqlmap(
    args: List[str],
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 600,
) -> int:
    """
    Run sqlmap with SOCKS5 proxy.

    Equivalent to psqlmap() in tools-wrapper.sh.

    Args:
        args: sqlmap arguments
        host: Proxy host
        port: Proxy port
        timeout: Command timeout in seconds (default: 600)

    Returns:
        sqlmap exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['sqlmap', f'--proxy=socks5://{host}:{port}'] + args,
        timeout=timeout,
    ).returncode


def pcs(
    args: List[str],
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 600,
) -> int:
    """
    Run any command via proxychains (generic wrapper).

    Equivalent to pcs() in tools-wrapper.sh.

    Args:
        args: Command and its arguments to run through proxychains
        host: Proxy host
        port: Proxy port
        timeout: Command timeout in seconds (default: 600)

    Returns:
        Command exit code
    """
    import shutil

    logger = get_logger()
    config = Config()
    port = port or _get_proxy_port(config)
    proxychains_conf = config.config_dir / 'proxychains.conf'
    if not check_proxy(host, port):
        return 1
    if args and not shutil.which(args[0]):
        logger.error(f"Command not found: {args[0]}")
        return 127
    return subprocess.run(
        ['proxychains4', '-q', '-f', str(proxychains_conf)] + args,
        timeout=timeout,
    ).returncode


# =============================================================================
# IP check utility
# =============================================================================


def ipcheck(
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 10,
) -> None:
    """
    Compare direct IP vs proxied IP.

    Equivalent to ipcheck() in tools-wrapper.sh.
    """
    config = Config()
    port = port or _get_proxy_port(config)

    # Direct IP
    result = subprocess.run(
        ['curl', '-s', '--connect-timeout', '5', 'https://ifconfig.me'],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    direct_ip = result.stdout.strip() if result.returncode == 0 else 'timeout'

    # Proxied IP
    result = subprocess.run(
        [
            'curl', '-s', '--connect-timeout', '5',
            '--socks5-hostname', f'{host}:{port}', 'https://ifconfig.me',
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    proxied_ip = result.stdout.strip() if result.returncode == 0 else 'not connected'

    print(f"Direct IP:  {direct_ip}")
    print(f"Proxied IP: {proxied_ip}")


# =============================================================================
# Quick recon helpers
# =============================================================================


def psub(
    domain: str,
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 300,
) -> int:
    """
    Quick subdomain enumeration through proxy.

    Requires subfinder + httpx. Uses phttpx() to verify live hosts.

    Equivalent to psub() in tools-wrapper.sh.

    Args:
        domain: Target domain (e.g. example.com)
        host: Proxy host
        port: Proxy port
        timeout: Command timeout in seconds (default: 300)

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
        stdout=subprocess.PIPE,
    )
    result = subprocess.run(
        ['httpx', '-proxy', f'socks5://{host}:{port}', '-silent'],
        stdin=subfinder.stdout,
        timeout=timeout,
    )
    subfinder.wait()
    return result.returncode


def pportscan(
    target: str,
    ports: str = '21,22,23,25,80,443,445,3306,3389,8080,8443',
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 300,
) -> int:
    """
    Quick port scan through proxy.

    Equivalent to pportscan() in tools-wrapper.sh.

    Args:
        target: Target host/IP
        ports: Comma-separated port list (default: common ports)
        host: Proxy host
        port: Proxy port
        timeout: Command timeout in seconds (default: 300)

    Returns:
        Exit code
    """
    config = Config()
    port = port or _get_proxy_port(config)

    if not target:
        print("Usage: pportscan target [ports]")
        return 1

    print(f"[*] Scanning {target} ports: {ports}")
    return pnmap(['-p', ports, target], host=host, port=port, timeout=timeout)


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
    cs-tools [options] <tool> [args...]

OPTIONS:
    --port PORT       SOCKS5 proxy port (default: from config)
    --host HOST       Proxy host (default: 127.0.0.1)
    --dry-run         Show command without executing
    --timeout SECS    Override default timeout
    -h, --help        Show this help

PROXIED TOOLS:
    pcurl       curl with SOCKS5
    pwget       wget via proxychains
    pnmap       nmap TCP connect scan (sanitizes incompatible flags)
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
    cs-tools --port 1081 pnmap -p 80,443 target.com
    cs-tools --dry-run pnmap -p 80 target.com
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

ALL_TOOLS = set(TOOL_COMMANDS) | {'ipcheck', 'psub', 'pportscan', 'help'}


def main_tools(argv=None):
    """
    Entry point for cs-tools command.

    Dispatches to proxied security tool wrappers.
    """
    logger = get_logger()

    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        show_help()
        return 0

    # Pre-parse global flags that appear before the tool name
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument('--port', type=int)
    pre_parser.add_argument('--host', default='127.0.0.1')
    pre_parser.add_argument('--dry-run', action='store_true')
    pre_parser.add_argument('--timeout', type=int)
    pre_parser.add_argument('-h', '--help', action='store_true')

    # Find split point: first non-option that is a known tool
    split = len(argv)
    for i, arg in enumerate(argv):
        if not arg.startswith('-') and arg in ALL_TOOLS:
            split = i
            break

    try:
        parsed, _ = pre_parser.parse_known_args(argv[:split])
    except SystemExit as e:
        return int(e.code) if e.code is not None else 2

    if parsed.help and split == len(argv):
        show_help()
        return 0

    if split == len(argv):
        # No known tool found in argv
        non_options = [a for a in argv if not a.startswith('-')]
        if non_options:
            logger.error(f"Unknown tool: {non_options[0]}. Run 'cs-tools help' for usage.")
            return 1
        show_help()
        return 0

    tool = argv[split]
    tool_args = argv[split + 1:]

    if tool == 'help':
        show_help()
        return 0

    host = parsed.host
    port = parsed.port
    dry_run = parsed.dry_run
    timeout = parsed.timeout

    # Single-arg commands
    if tool == 'ipcheck':
        if dry_run:
            print(f"[dry-run] ipcheck(host={host!r}, port={port!r})")
            return 0
        ipcheck(host=host, port=port, timeout=timeout or 10)
        return 0

    if tool == 'psub':
        if not tool_args:
            print("Usage: cs-tools psub domain.com")
            return 1
        if dry_run:
            print(
                f"[dry-run] psub(domain={tool_args[0]!r}, host={host!r}, port={port!r})"
            )
            return 0
        return psub(tool_args[0], host=host, port=port, timeout=timeout or 300)

    if tool == 'pportscan':
        if not tool_args:
            print("Usage: cs-tools pportscan target [ports]")
            return 1
        ports = (
            tool_args[1]
            if len(tool_args) > 1
            else '21,22,23,25,80,443,445,3306,3389,8080,8443'
        )
        if dry_run:
            print(
                f"[dry-run] pportscan(target={tool_args[0]!r}, ports={ports!r}, "
                f"host={host!r}, port={port!r})"
            )
            return 0
        return pportscan(
            tool_args[0], ports, host=host, port=port, timeout=timeout or 300
        )

    if tool in TOOL_COMMANDS:
        _, fn = TOOL_COMMANDS[tool]
        if dry_run:
            print(
                f"[dry-run] {tool}(args={tool_args!r}, host={host!r}, port={port!r})"
            )
            return 0
        try:
            return fn(tool_args, host=host, port=port, timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.error(f"{tool} timed out")
            return 124

    logger.error(f"Unknown tool: {tool}. Run 'cs-tools help' for usage.")
    return 1


if __name__ == '__main__':
    sys.exit(main_tools())
