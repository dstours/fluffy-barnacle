#!/usr/bin/env python3
"""
WireGuard setup helpers: privilege checks, directory setup, key generation,
and codespace selection/management.

Extracted from wireguard.py for modularity.
"""

import os
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .github import GitHubManager
from .templates import WG_REMOTE_SETUP_SCRIPT as _REMOTE_SETUP_SCRIPT
from .utils import Config, get_logger


def _check_root() -> None:
    """Raise RuntimeError if not running as root."""
    if os.geteuid() != 0:
        raise RuntimeError("This command requires root privileges. Run with sudo.")


def _run_gh(args: list, sudo_user: Optional[str] = None,
            **kwargs) -> subprocess.CompletedProcess:
    """
    Run gh command, delegating to original user when running via sudo.

    Equivalent to run_gh() in cs-wg.sh.
    """
    if os.geteuid() == 0 and sudo_user:
        cmd = ['sudo', '-u', sudo_user, 'gh'] + args
    else:
        cmd = ['gh'] + args
    return subprocess.run(cmd, **kwargs)


def _ensure_dirs(wg_dir: Path, config_dir: Path, sudo_user: Optional[str] = None) -> None:
    """
    Create WireGuard key/config directory with correct permissions.

    Equivalent to ensure_dirs() in cs-wg.sh.
    """
    wg_dir.mkdir(parents=True, exist_ok=True)
    try:
        config_dir.chmod(0o700)
        wg_dir.chmod(0o700)
    except OSError:
        pass

    if os.geteuid() == 0 and sudo_user:
        subprocess.run(['chown', '-R', f'{sudo_user}:{sudo_user}', str(config_dir)],
                       capture_output=True)


def generate_keys(wg_dir: Path) -> None:
    """
    Generate local and remote WireGuard keypairs if they don't exist.

    Keys are stored as plain text files with 0o600 permissions.
    For production use, consider encrypting the key directory at rest.
    """
    logger = get_logger()

    # Local (client) keys
    local_priv = wg_dir / 'local_private.key'
    local_pub = wg_dir / 'local_public.key'
    if not local_priv.exists():
        result = subprocess.run(['wg', 'genkey'], capture_output=True, text=True, check=True)
        private_key = result.stdout.strip()
        local_priv.write_text(private_key)
        local_priv.chmod(0o600)

        result = subprocess.run(['wg', 'pubkey'], input=private_key,
                                capture_output=True, text=True, check=True)
        local_pub.write_text(result.stdout.strip())
        logger.info("Generated local keypair")
    else:
        logger.debug("Local keys already exist")

    # Remote (codespace) keys
    remote_priv = wg_dir / 'remote_private.key'
    remote_pub = wg_dir / 'remote_public.key'
    if not remote_priv.exists():
        result = subprocess.run(['wg', 'genkey'], capture_output=True, text=True, check=True)
        private_key = result.stdout.strip()
        remote_priv.write_text(private_key)
        remote_priv.chmod(0o600)

        result = subprocess.run(['wg', 'pubkey'], input=private_key,
                                capture_output=True, text=True, check=True)
        remote_pub.write_text(result.stdout.strip())
        logger.info("Generated remote keypair")
    else:
        logger.debug("Remote keys already exist")


def select_codespace(gh: GitHubManager, config: Config,
                     sudo_user: Optional[str] = None) -> str:
    """
    Select or auto-detect a Codespace to use.

    Equivalent to select_codespace() in cs-wg.sh.

    Returns:
        Codespace name

    Raises:
        RuntimeError: If no Codespace can be selected
    """
    logger = get_logger()

    # Use already-configured name
    cs_name = config.codespace_name or os.environ.get('CODESPACE_NAME', '')
    if cs_name:
        return cs_name

    result = _run_gh(
        ['codespace', 'list', '--json', 'name,state,repository'],
        sudo_user=sudo_user,
        capture_output=True, text=True
    )

    import json
    try:
        cs_list = json.loads(result.stdout or '[]')
    except json.JSONDecodeError:
        cs_list = []

    if not cs_list:
        raise RuntimeError("No Codespaces found. Create one first: gh codespace create")

    if len(cs_list) == 1:
        cs_name = cs_list[0]['name']
        logger.info(f"Auto-selected: {cs_name}")
    else:
        logger.info("Available Codespaces:")
        print()
        for i, cs in enumerate(cs_list, 1):
            print(f"  {i:2}) {cs['name']:<40} {cs.get('state','?'):<12} {cs.get('repository','')}")
        print()

        selection = input("Enter number or name (Enter for most recent): ").strip()

        if not selection:
            cs_name = cs_list[0]['name']
        elif selection.isdigit():
            idx = int(selection) - 1
            if 0 <= idx < len(cs_list):
                cs_name = cs_list[idx]['name']
            else:
                raise RuntimeError(f"Invalid selection: {selection}")
        else:
            cs_name = selection

    if not cs_name:
        raise RuntimeError("No Codespace selected")

    # Persist selection
    cs_file = config.config_dir / 'current_codespace'
    cs_file.write_text(f'CODESPACE_NAME="{cs_name}"\n')

    return cs_name


def ensure_codespace_running(cs_name: str, gh: GitHubManager,
                              sudo_user: Optional[str] = None) -> None:
    """
    Start the Codespace if it isn't running and wait for it to be Available.

    Equivalent to ensure_codespace_running() in cs-wg.sh.
    """
    logger = get_logger()
    logger.debug(f"Checking Codespace state for: {cs_name}")

    result = _run_gh(
        ['codespace', 'list', '--json', 'name,state',
         '-q', f'.[] | select(.name=="{cs_name}") | .state'],
        sudo_user=sudo_user,
        capture_output=True, text=True
    )
    state = result.stdout.strip()
    logger.debug(f"Codespace state: {state}")

    if not state:
        raise RuntimeError(f"Codespace '{cs_name}' not found")

    if state != 'Available':
        logger.info(f"Codespace state is '{state}', starting it...")
        _run_gh(['codespace', 'start', '-c', cs_name], sudo_user=sudo_user, check=True)

        for attempt in range(30):
            result = _run_gh(
                ['codespace', 'list', '--json', 'name,state',
                 '-q', f'.[] | select(.name=="{cs_name}") | .state'],
                sudo_user=sudo_user,
                capture_output=True, text=True
            )
            state = result.stdout.strip()
            if state == 'Available':
                logger.info("Codespace is now available")
                return
            logger.debug(f"Waiting for Codespace... (attempt {attempt}, state: {state})")
            time.sleep(3)
        raise RuntimeError("Codespace failed to start within timeout")
    else:
        logger.info("Codespace is already running")


# =============================================================================
# Configuration Generation
# =============================================================================

from .wg_constants import (
    WG_INTERFACE as _WG_INTERFACE,
    WG_PORT as _WG_PORT,
    WG_LOCAL_IP as _WG_LOCAL_IP,
    WG_REMOTE_IP as _WG_REMOTE_IP,
    WG_NETWORK as _WG_NETWORK,
)


def generate_local_config(wg_dir: Path, interface: str = _WG_INTERFACE,
                           local_ip: str = _WG_LOCAL_IP, remote_ip: str = _WG_REMOTE_IP,
                           port: int = _WG_PORT) -> None:
    """
    Write the local WireGuard interface config file.

    Equivalent to generate_local_config() in cs-wg.sh.
    """
    logger = get_logger()
    local_priv = (wg_dir / 'local_private.key').read_text().strip()
    remote_pub = (wg_dir / 'remote_public.key').read_text().strip()
    remote_host = remote_ip.split('/')[0]

    config_path = wg_dir / f'{interface}.conf'
    config_path.write_text(
        f"# cs-wg local configuration\n"
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"[Interface]\n"
        f"PrivateKey = {local_priv}\n"
        f"Address = {local_ip}\n"
        f"# DNS = 1.1.1.1  # Uncomment to route DNS through tunnel\n\n"
        f"[Peer]\n"
        f"PublicKey = {remote_pub}\n"
        f"AllowedIPs = {remote_host}/32\n"
        f"# AllowedIPs = 0.0.0.0/0  # Uncomment to route ALL traffic through tunnel\n"
        f"Endpoint = 127.0.0.1:{port}\n"
        f"PersistentKeepalive = 25\n"
    )
    config_path.chmod(0o600)
    logger.info(f"Generated local config: {config_path}")


def build_remote_setup_script(wg_dir: Path, remote_ip: str = _WG_REMOTE_IP,
                               local_ip: str = _WG_LOCAL_IP, network: str = _WG_NETWORK,
                               port: int = _WG_PORT) -> str:
    """
    Build the Bash setup script to upload and run in the Codespace.

    Equivalent to generate_remote_setup_script() in cs-wg.sh.

    Returns:
        Complete Bash script content with keys embedded.
    """
    remote_priv = (wg_dir / 'remote_private.key').read_text().strip()
    local_pub = (wg_dir / 'local_public.key').read_text().strip()
    local_ip_host = local_ip.split('/')[0]
    remote_ip_host = remote_ip.split('/')[0]

    return _REMOTE_SETUP_SCRIPT.format(
        remote_private_key=remote_priv,
        wg_remote_ip=remote_ip,
        wg_port=port,
        wg_network=network,
        local_public_key=local_pub,
        local_ip_host=local_ip_host,
        remote_ip_host=remote_ip_host,
    )
