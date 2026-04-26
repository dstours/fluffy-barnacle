#!/usr/bin/env python3
"""
WireGuard route management.

Functions for routing specific or all traffic through the WireGuard tunnel.
Extracted from wireguard.py for modularity.
"""

import os
import re
import subprocess
from pathlib import Path

from .utils import Config, get_logger
from .wg_constants import WG_INTERFACE

# GitHub/Azure IP ranges to bypass when routing all traffic through tunnel.
# These keep the SSH tunnel and gh CLI alive when route_all() is active.
# NOTE: Azure ranges change frequently. If SSH drops after route_all(),
# add your specific region CIDR here.
_BYPASS_ROUTES = [
    # GitHub (well-documented, stable)
    '140.82.112.0/20',   # GitHub web/API
    '192.30.252.0/22',   # GitHub pages
    '185.199.108.0/22',  # GitHub pages
    # Azure (narrowed from /8 to /16 for common datacenter regions)
    '20.37.0.0/16',      # Azure East US
    '20.38.0.0/16',      # Azure East US 2
    '20.42.0.0/16',      # Azure West Europe
    '20.43.0.0/16',      # Azure North Europe
    '20.195.0.0/16',     # Azure Southeast Asia
    '52.96.0.0/16',      # Azure West US 2
    '52.136.0.0/16',     # Azure West Central US
    '52.147.0.0/16',     # Azure East US
    '52.165.0.0/16',     # Azure East US 2
    '52.166.0.0/16',     # Azure Central US
    '52.239.0.0/16',     # Azure North Central US
]


def _check_root() -> None:
    """Raise RuntimeError if not running as root."""
    if os.geteuid() != 0:
        raise RuntimeError("This command requires root privileges. Run with sudo.")


def add_route(target: str, interface: str = WG_INTERFACE) -> None:
    """Route a specific IP/CIDR or domain through the WireGuard interface."""
    logger = get_logger()

    if not target:
        raise ValueError("Usage: cs-wg route add <ip/cidr or domain>")

    if not re.match(r'^\d+\.\d+\.\d+\.\d+', target):
        result = subprocess.run(['dig', '+short', target], capture_output=True, text=True)
        ip = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ''
        if not ip:
            raise RuntimeError(f"Could not resolve: {target}")
        logger.info(f"Resolved {target} -> {ip}")
        target = ip

    if '/' not in target:
        target = f"{target}/32"

    result = subprocess.run(['ip', 'route', 'add', target, 'dev', interface], capture_output=True)
    if result.returncode != 0:
        logger.warning(f"Route may already exist: {target}")
    else:
        logger.info(f"Added route: {target} via {interface}")


def del_route(target: str, interface: str = WG_INTERFACE) -> None:
    """Remove a route from the WireGuard interface."""
    logger = get_logger()

    if not target:
        raise ValueError("Usage: cs-wg route del <ip/cidr>")

    if '/' not in target:
        target = f"{target}/32"

    subprocess.run(['ip', 'route', 'del', target, 'dev', interface], capture_output=True)
    logger.info(f"Removed route: {target}")


def route_all(config: Config, interface: str = WG_INTERFACE) -> None:
    """
    Route ALL traffic through the WireGuard tunnel.

    Adds 0.0.0.0/1 and 128.0.0.0/1 default routes, with bypass routes
    for GitHub/Azure IPs to keep the SSH tunnel alive.
    """
    logger = get_logger()
    _check_root()

    result = subprocess.run(['ip', 'link', 'show', interface], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"WireGuard interface {interface} not found. Run 'cs-wg up' first.")

    logger.warning("This will route ALL traffic through the Codespace!")
    logger.warning("The SSH tunnel and local network will be preserved.")
    confirm = input("Continue? [y/N] ").strip().lower()
    if confirm not in ('y', 'yes'):
        return

    result = subprocess.run(['ip', 'route'], capture_output=True, text=True)
    default_line = next((l for l in result.stdout.splitlines() if l.startswith('default')), '')
    parts = default_line.split()
    try:
        gw_idx = parts.index('via') + 1
        dev_idx = parts.index('dev') + 1
        default_gw = parts[gw_idx]
        default_dev = parts[dev_idx]
    except (ValueError, IndexError):
        raise RuntimeError("Could not determine default gateway")

    logger.info(f"Default gateway: {default_gw} via {default_dev}")

    wg_dir = config.config_dir / 'wireguard'
    (wg_dir / 'original_route').write_text(f"{default_gw} {default_dev}")

    try:
        import shutil
        shutil.copy2('/etc/resolv.conf', str(wg_dir / 'resolv.conf.backup'))
    except OSError:
        pass

    ipv6_result = subprocess.run(['cat', '/proc/sys/net/ipv6/conf/all/disable_ipv6'],
                                  capture_output=True, text=True)
    (wg_dir / 'ipv6_state.backup').write_text(ipv6_result.stdout.strip() or '1')
    logger.info("Disabling IPv6 (tunnel is IPv4 only)...")
    for key in ['net.ipv6.conf.all.disable_ipv6', 'net.ipv6.conf.default.disable_ipv6',
                'net.ipv6.conf.lo.disable_ipv6']:
        subprocess.run(['sysctl', '-w', f'{key}=1'], capture_output=True)

    logger.info("Adding bypass routes for GitHub/Azure...")
    for cidr in _BYPASS_ROUTES:
        subprocess.run(['ip', 'route', 'add', cidr, 'via', default_gw,
                        'dev', default_dev], capture_output=True)

    kernel_result = subprocess.run(['ip', 'route'], capture_output=True, text=True)
    for line in kernel_result.stdout.splitlines():
        if 'proto kernel' in line and default_dev in line:
            local_net = line.split()[0]
            if local_net and local_net != 'default':
                logger.info(f"Preserving local network: {local_net}")
                subprocess.run(['ip', 'route', 'add', local_net, 'via', default_gw,
                                'dev', default_dev], capture_output=True)
            break

    logger.info("Routing all traffic through tunnel...")
    subprocess.run(['ip', 'route', 'add', '0.0.0.0/1', 'dev', interface], check=True)
    subprocess.run(['ip', 'route', 'add', '128.0.0.0/1', 'dev', interface], check=True)

    logger.info("Setting DNS to use tunnel...")
    Path('/etc/resolv.conf').write_text("nameserver 1.1.1.1\nnameserver 8.8.8.8\n")

    logger.info("All traffic now routed through Codespace!")
    logger.info("Test with: curl https://ifconfig.me")
    logger.info("Restore with: sudo cs-wg route restore")


def route_restore(config: Config, interface: str = WG_INTERFACE) -> None:
    """Restore normal routing after route_all()."""
    logger = get_logger()
    _check_root()

    logger.info("Restoring default routing...")

    subprocess.run(['ip', 'route', 'del', '0.0.0.0/1', 'dev', interface], capture_output=True)
    subprocess.run(['ip', 'route', 'del', '128.0.0.0/1', 'dev', interface], capture_output=True)

    for cidr in _BYPASS_ROUTES:
        subprocess.run(['ip', 'route', 'del', cidr], capture_output=True)

    wg_dir = config.config_dir / 'wireguard'
    resolv_backup = wg_dir / 'resolv.conf.backup'
    if resolv_backup.exists():
        import shutil
        shutil.copy2(str(resolv_backup), '/etc/resolv.conf')
        resolv_backup.unlink()
        logger.info("DNS restored")

    ipv6_backup = wg_dir / 'ipv6_state.backup'
    if ipv6_backup.exists():
        was_disabled = ipv6_backup.read_text().strip()
        if was_disabled == '0':
            logger.info("Re-enabling IPv6...")
            for key in ['net.ipv6.conf.all.disable_ipv6', 'net.ipv6.conf.default.disable_ipv6',
                        'net.ipv6.conf.lo.disable_ipv6']:
                subprocess.run(['sysctl', '-w', f'{key}=0'], capture_output=True)
        ipv6_backup.unlink()

    logger.info("Default routing restored")
