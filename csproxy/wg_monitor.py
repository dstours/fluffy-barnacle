#!/usr/bin/env python3
"""
WireGuard traffic monitoring via tcpdump.

Provides colored output for different traffic types (HTTP, DNS, SSH, etc.).
Extracted from wireguard.py for modularity.
"""

import os
import re
import subprocess
from typing import Optional

from .utils import get_logger
from .wg_constants import WG_INTERFACE

# ANSI color codes
_RED = '\033[31m'
_GREEN = '\033[32m'
_YELLOW = '\033[33m'
_CYAN = '\033[36m'
_WHITE = '\033[37m'
_RESET = '\033[0m'


def _check_root() -> None:
    """Raise RuntimeError if not running as root."""
    if os.geteuid() != 0:
        raise RuntimeError("This command requires root privileges. Run with sudo.")


def monitor_traffic(mode: Optional[str], interface: str = WG_INTERFACE) -> None:
    """
    Monitor traffic on the WireGuard interface using tcpdump.

    Modes: http, dns, hosts, conns, all, leak (None = summary)
    """
    logger = get_logger()
    _check_root()

    result = subprocess.run(['ip', 'link', 'show', interface], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"WireGuard interface {interface} not found. Run 'cs-wg up' first.")

    print(f"=== Traffic Monitor on {interface} ===")
    print("Press Ctrl+C to stop\n")

    proc = None
    try:
        if mode in ('http', 'web'):
            logger.info("Monitoring HTTP/HTTPS traffic...")
            proc = subprocess.Popen(
                ['tcpdump', '-i', interface, '-n', '-l',
                 'tcp port 80 or tcp port 443', '-t', '-q'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            for line in proc.stdout:
                line = line.rstrip()
                if '.80:' in line or ' .80 ' in line:
                    print(f"{_GREEN}[HTTP] {_RESET} {line}")
                elif '.443:' in line or ' .443 ' in line:
                    print(f"{_YELLOW}[HTTPS]{_RESET} {line}")
                else:
                    print(line)

        elif mode == 'dns':
            logger.info("Monitoring DNS traffic...")
            proc = subprocess.Popen(
                ['tcpdump', '-i', interface, '-n', '-l', 'udp port 53', '-t'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            for line in proc.stdout:
                print(f"{_CYAN}[DNS]{_RESET}  {line.rstrip()}")

        elif mode == 'hosts':
            logger.info("Monitoring unique destination hosts...")
            proc = subprocess.Popen(
                ['tcpdump', '-i', interface, '-n', '-l', 'tcp or udp', '-t', '-q'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            seen: set = set()
            for line in proc.stdout:
                m = re.search(r'> (\d+\.\d+\.\d+\.\d+)', line)
                if m:
                    ip = m.group(1)
                    if not ip.startswith('10.') and ip not in seen:
                        seen.add(ip)
                        print(f"{_GREEN}[NEW]{_RESET}  {ip}")

        elif mode in ('conns', 'connections'):
            logger.info("Monitoring new TCP connections...")
            proc = subprocess.Popen(
                ['tcpdump', '-i', interface, '-n', '-l',
                 'tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0', '-t'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            for line in proc.stdout:
                m = re.search(r'(\S+) > (\S+)', line)
                if m:
                    print(f"{_GREEN}[CONN]{_RESET} {m.group(1)} -> {m.group(2)}")

        elif mode == 'all':
            logger.info("Monitoring all traffic (summary)...")
            subprocess.run(['tcpdump', '-i', interface, '-n', '-l', '-t', '-q'])

        elif mode == 'leak':
            logger.info("Monitoring for traffic leaks on eth0...")
            print(f"{_YELLOW}Traffic on eth0 that should be going through tunnel:{_RESET}")
            bypass = ('net 140.82.112.0/20 or net 192.30.252.0/22 or '
                      'net 185.199.108.0/22 or net 20.0.0.0/8 or net 52.0.0.0/8 or '
                      'net 51.0.0.0/8 or net 13.0.0.0/8 or net 40.0.0.0/8 or '
                      'net 104.0.0.0/8 or net 192.168.0.0/16 or net 10.0.0.0/8 or '
                      'net 172.16.0.0/12 or port 22')
            proc = subprocess.Popen(
                ['tcpdump', '-i', 'eth0', '-n', '-l', f'not ({bypass})', '-t', '-q'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            for line in proc.stdout:
                print(f"{_RED}[LEAK?]{_RESET} {line.rstrip()}")

        else:
            # Default summary
            logger.info("Monitoring traffic summary (use 'http', 'dns', 'hosts', 'conns', 'all', or 'leak')...")
            proc = subprocess.Popen(
                ['tcpdump', '-i', interface, '-n', '-l', '-t', '-q'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            for line in proc.stdout:
                line = line.rstrip()
                if re.search(r'\.(80:|80 >)', line):
                    prefix = f"{_GREEN}[HTTP] {_RESET}"
                elif re.search(r'\.(443:|443 >)', line):
                    prefix = f"{_YELLOW}[HTTPS]{_RESET}"
                elif re.search(r'\.(53:|53 >)', line):
                    prefix = f"{_CYAN}[DNS]  {_RESET}"
                elif re.search(r'\.(22:|22 >)', line):
                    prefix = f"\033[35m[SSH]  {_RESET}"
                else:
                    prefix = f"{_WHITE}[TCP]  {_RESET}"
                print(f"{prefix} {line}")

    except KeyboardInterrupt:
        pass
    finally:
        if proc is not None:
            proc.terminate()
