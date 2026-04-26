#!/usr/bin/env python3
"""
cs-wg - WireGuard tunnel through GitHub Codespaces.

Sets up a WireGuard VPN between the local machine and a Codespace,
enabling full transparent proxying of all traffic.
"""

import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path

from .github import GitHubManager
from .utils import Config, get_logger

# Re-export from extracted modules for backward compatibility
from .templates import WG_REMOTE_SETUP_SCRIPT as _REMOTE_SETUP_SCRIPT  # noqa: F401
from .wg_routes import (  # noqa: F401
    add_route, del_route, route_all, route_restore,
    _BYPASS_ROUTES,
)
from .wg_monitor import monitor_traffic  # noqa: F401
from .wg_setup import (  # noqa: F401
    _check_root, _run_gh, _ensure_dirs, generate_keys,
    generate_local_config, build_remote_setup_script as _build_remote_setup_script,
    select_codespace as _select_codespace,
    ensure_codespace_running as _ensure_codespace_running,
)

VERSION = "1.0.0"

from .wg_constants import (
    WG_INTERFACE,
    WG_PORT,
    WG_LOCAL_IP,
    WG_REMOTE_IP,
    WG_NETWORK,
    TCP_RELAY_PORT,
)


def start_tunnel(config: Config, gh: GitHubManager) -> None:
    """
    Start the WireGuard tunnel: keys, codespace setup, port forwarding, interface.

    Equivalent to start_tunnel() in cs-wg.sh.
    """
    logger = get_logger()
    sudo_user = os.environ.get('SUDO_USER') if os.geteuid() == 0 else None

    _check_root()

    wg_dir = config.config_dir / 'wireguard'
    _ensure_dirs(wg_dir, config.config_dir, sudo_user)

    # Clear cached codespace for fresh selection
    cs_file = config.config_dir / 'current_codespace'
    cs_file.unlink(missing_ok=True)

    # Phase 1: Keys
    logger.info("Generating WireGuard keys...")
    generate_keys(wg_dir)

    # Phase 2: Codespace
    logger.info("Selecting Codespace...")
    cs_name = _select_codespace(gh, config, sudo_user)
    logger.info(f"Using Codespace: {cs_name}")
    logger.info("Ensuring Codespace is running...")
    _ensure_codespace_running(cs_name, gh, sudo_user)

    # Test SSH connectivity
    logger.info("Testing SSH connection...")
    result = _run_gh(['codespace', 'ssh', '-c', cs_name, '--', 'echo SSH OK'],
                     sudo_user=sudo_user, capture_output=True, text=True)
    if 'SSH OK' not in result.stdout:
        logger.warning("First SSH attempt failed, retrying...")
        time.sleep(3)
        result = _run_gh(['codespace', 'ssh', '-c', cs_name, '--', 'echo SSH OK'],
                         sudo_user=sudo_user, capture_output=True, text=True)
        if 'SSH OK' not in result.stdout:
            raise RuntimeError("Cannot establish SSH connection to codespace")
    logger.info("SSH connection verified")

    # Phase 3: Remote WireGuard setup
    logger.info(f"Setting up WireGuard tunnel to {cs_name}...")
    generate_local_config(wg_dir)

    logger.info("Configuring WireGuard in Codespace (this takes ~30 seconds)...")
    script = _build_remote_setup_script(wg_dir)

    # Upload setup script via stdin
    setup_path = '/tmp/setup_wg.sh'
    gh_cmd = ['gh', 'codespace', 'ssh', '-c', cs_name, '--',
               f'cat > {shlex.quote(setup_path)} && chmod +x {shlex.quote(setup_path)}']
    if sudo_user and os.geteuid() == 0:
        gh_cmd = ['sudo', '-u', sudo_user] + gh_cmd

    result = subprocess.run(gh_cmd, input=script.encode(), capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to copy setup script to codespace: "
                           f"{result.stderr.decode().strip()}")

    run_cmd = ['gh', 'codespace', 'ssh', '-c', cs_name, '--', setup_path]
    if sudo_user and os.geteuid() == 0:
        run_cmd = ['sudo', '-u', sudo_user] + run_cmd

    result = subprocess.run(run_cmd)
    if result.returncode != 0:
        raise RuntimeError("Failed to run WireGuard setup in codespace")

    # Wipe the setup script immediately after execution to avoid leaving
    # private keys on the Codespace filesystem.
    wipe_cmd = ['gh', 'codespace', 'ssh', '-c', cs_name, '--',
                f'shred -u {shlex.quote(setup_path)} 2>/dev/null || rm -f {shlex.quote(setup_path)}']
    if sudo_user and os.geteuid() == 0:
        wipe_cmd = ['sudo', '-u', sudo_user] + wipe_cmd
    subprocess.run(wipe_cmd, capture_output=True)

    time.sleep(2)

    # Phase 4: SSH tunnel for UDP relay
    logger.info("Setting up SSH tunnel for UDP relay...")

    # Kill any existing local relay processes
    subprocess.run(['pkill', '-f', f'socat.*UDP.*{shlex.quote(str(WG_PORT))}'], capture_output=True)
    subprocess.run(['pkill', '-f', f'socat.*{shlex.quote(str(TCP_RELAY_PORT))}'], capture_output=True)

    # Verify remote socat is running
    logger.info("Verifying remote relay...")
    verify_cmd = ['gh', 'codespace', 'ssh', '-c', cs_name, '--',
                  f"pgrep -f 'socat.*TCP-LISTEN.*{shlex.quote(str(TCP_RELAY_PORT))}' > /dev/null && echo 'relay running'"]
    if sudo_user and os.geteuid() == 0:
        verify_cmd = ['sudo', '-u', sudo_user] + verify_cmd

    result = subprocess.run(verify_cmd, capture_output=True, text=True)
    if 'relay running' in result.stdout:
        logger.info("Remote socat relay confirmed")
    else:
        logger.warning("Remote socat may not be running, attempting to start...")
        start_socat_cmd = ['gh', 'codespace', 'ssh', '-c', cs_name, '--',
                           f'nohup socat TCP-LISTEN:{shlex.quote(str(TCP_RELAY_PORT))},reuseaddr,fork '
                           f'UDP:127.0.0.1:{shlex.quote(str(WG_PORT))} > /tmp/socat_relay.log 2>&1 &']
        if sudo_user and os.geteuid() == 0:
            start_socat_cmd = ['sudo', '-u', sudo_user] + start_socat_cmd
        subprocess.run(start_socat_cmd, capture_output=True)
        time.sleep(2)

    time.sleep(1)

    # Check if SSH tunnel port forward is already active
    logger.info("Starting SSH tunnel with port forward...")
    result = subprocess.run(['ss', '-tln'], capture_output=True, text=True)
    if f':{TCP_RELAY_PORT}' in result.stdout:
        logger.info(f"SSH tunnel already running on port {TCP_RELAY_PORT}")
    else:
        logger.warning(f"SSH tunnel not running on port {TCP_RELAY_PORT}")
        print()
        print("The SSH tunnel must be started as your regular user (not root).")
        print("Please run this in another terminal:")
        print()
        print(f"  gh codespace ssh -c {shlex.quote(cs_name)} -- "
              f"-T -L 127.0.0.1:{TCP_RELAY_PORT}:127.0.0.1:{TCP_RELAY_PORT} -N &")
        print()
        input("Then press Enter to continue...")

        result = subprocess.run(['ss', '-tln'], capture_output=True, text=True)
        if f':{TCP_RELAY_PORT}' not in result.stdout:
            raise RuntimeError("SSH tunnel still not running. Please start it first.")
        logger.info("SSH tunnel detected")

    # Start local socat: UDP listener -> TCP to SSH tunnel
    logger.info("Starting local socat relay...")
    socat_proc = subprocess.Popen(
        ['socat', f'UDP-LISTEN:{WG_PORT},reuseaddr,fork',
         f'TCP:127.0.0.1:{TCP_RELAY_PORT}']
    )
    socat_pid_file = config.config_dir / 'wireguard' / 'socat_local.pid'
    socat_pid_file.write_text(str(socat_proc.pid))
    time.sleep(1)

    # Phase 5: Bring up local WireGuard interface
    logger.info("Bringing up local WireGuard interface...")

    subprocess.run(['ip', 'link', 'del', WG_INTERFACE], capture_output=True)
    subprocess.run(['ip', 'link', 'add', WG_INTERFACE, 'type', 'wireguard'], check=True)

    remote_pub = (wg_dir / 'remote_public.key').read_text().strip()
    subprocess.run([
        'wg', 'set', WG_INTERFACE,
        'private-key', str(wg_dir / 'local_private.key'),
        'peer', remote_pub,
        'allowed-ips', '0.0.0.0/0',
        'endpoint', f'127.0.0.1:{WG_PORT}',
        'persistent-keepalive', '25',
    ], check=True)

    subprocess.run(['ip', 'addr', 'add', WG_LOCAL_IP, 'dev', WG_INTERFACE], check=True)
    subprocess.run(['ip', 'link', 'set', WG_INTERFACE, 'up'], check=True)
    time.sleep(2)

    # Phase 6: Test connectivity
    remote_host = WG_REMOTE_IP.split('/')[0]
    logger.info("Testing tunnel connectivity...")
    result = subprocess.run(['ping', '-c', '1', '-W', '3', remote_host], capture_output=True)
    if result.returncode == 0:
        logger.info("Tunnel is UP and working!")
    else:
        logger.warning("Ping failed - may still work (ICMP could be blocked)")

    print()
    show_status(config, gh)


def stop_tunnel(config: Config, gh: GitHubManager) -> None:
    """
    Stop the WireGuard tunnel and clean up all local/remote state.

    Equivalent to stop_tunnel() in cs-wg.sh.
    """
    logger = get_logger()

    # Load saved codespace name if not in config
    cs_name = config.codespace_name or os.environ.get('CODESPACE_NAME', '')
    if not cs_name:
        cs_file = config.config_dir / 'current_codespace'
        if cs_file.exists():
            for line in cs_file.read_text().splitlines():
                m = re.match(r'CODESPACE_NAME="?([^"]+)"?', line)
                if m:
                    cs_name = m.group(1)
                    break

    sudo_user = os.environ.get('SUDO_USER') if os.geteuid() == 0 else None

    logger.info("Stopping WireGuard tunnel and cleaning up...")

    # Restore routing if modified
    result = subprocess.run(['ip', 'route'], capture_output=True, text=True)
    if f'0.0.0.0/1.*{WG_INTERFACE}' in result.stdout or \
       re.search(rf'0\.0\.0\.0/1.*{re.escape(WG_INTERFACE)}', result.stdout):
        logger.info("Restoring routing...")
        subprocess.run(['ip', 'route', 'del', '0.0.0.0/1', 'dev', WG_INTERFACE],
                       capture_output=True)
        subprocess.run(['ip', 'route', 'del', '128.0.0.0/1', 'dev', WG_INTERFACE],
                       capture_output=True)
        for cidr in _BYPASS_ROUTES:
            subprocess.run(['ip', 'route', 'del', cidr], capture_output=True)

    # Restore DNS if backed up
    wg_dir = config.config_dir / 'wireguard'
    resolv_backup = wg_dir / 'resolv.conf.backup'
    if resolv_backup.exists():
        logger.info("Restoring DNS...")
        try:
            import shutil
            shutil.copy2(str(resolv_backup), '/etc/resolv.conf')
            resolv_backup.unlink()
        except OSError as e:
            logger.warning(f"Could not restore DNS: {e}")

    # Remove WireGuard interface
    result = subprocess.run(['ip', 'link', 'show', WG_INTERFACE], capture_output=True)
    if result.returncode == 0:
        if os.geteuid() != 0:
            logger.warning(f"Need root to fully clean up. Run: sudo cs-wg down")
        else:
            subprocess.run(['ip', 'link', 'del', WG_INTERFACE], capture_output=True)
            logger.info(f"Removed {WG_INTERFACE} interface")

    # Stop local socat
    logger.info("Stopping local socat relay...")
    socat_pid_file = wg_dir / 'socat_local.pid'
    if socat_pid_file.exists():
        try:
            pid = int(socat_pid_file.read_text().strip())
            os.kill(pid, 0)  # validate PID exists before signaling
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
        socat_pid_file.unlink(missing_ok=True)
    subprocess.run(['pkill', '-f', f'socat.*UDP.*{shlex.quote(str(WG_PORT))}'], capture_output=True)
    subprocess.run(['pkill', '-f', f'socat.*{shlex.quote(str(WG_PORT))}'], capture_output=True)
    subprocess.run(['pkill', '-f', f'socat.*{shlex.quote(str(TCP_RELAY_PORT))}'], capture_output=True)

    # Stop SSH tunnel
    logger.info("Stopping SSH tunnel...")
    ssh_pid_file = wg_dir / 'ssh_tunnel.pid'
    if ssh_pid_file.exists():
        try:
            pid = int(ssh_pid_file.read_text().strip())
            os.kill(pid, 0)  # validate PID exists before signaling
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
        ssh_pid_file.unlink(missing_ok=True)
    subprocess.run(['pkill', '-f', 'gh.*codespace.*ssh.*-L'], capture_output=True)
    subprocess.run(['pkill', '-f', f'ssh.*{shlex.quote(str(TCP_RELAY_PORT))}:127.0.0.1'], capture_output=True)
    subprocess.run(['fuser', '-k', f'{shlex.quote(str(TCP_RELAY_PORT))}/tcp'], capture_output=True)

    # Stop remote WireGuard if codespace accessible
    if cs_name:
        logger.info(f"Cleaning up codespace ({cs_name})...")
        cleanup_cmd = ['gh', 'codespace', 'ssh', '-c', cs_name, '--',
                       f'sudo wg-quick down wg0 2>/dev/null || true; '
                       f'pkill -f socat.*TCP-LISTEN.*{shlex.quote(str(TCP_RELAY_PORT))} 2>/dev/null || true']
        if sudo_user and os.geteuid() == 0:
            cleanup_cmd = ['sudo', '-u', sudo_user] + cleanup_cmd
        subprocess.run(cleanup_cmd, capture_output=True)

    # Clean up state files
    cs_file = config.config_dir / 'current_codespace'
    cs_file.unlink(missing_ok=True)

    logger.info("Tunnel stopped and cleaned up")
    logger.info("")
    logger.info("Verify with:")
    logger.info(f"  ip link show {WG_INTERFACE}  # should fail")
    logger.info("  ss -tln | grep 51821        # should be empty")
    logger.info("  curl https://ifconfig.me    # should show your real IP")


def show_status(config: Config, gh: GitHubManager) -> None:
    """
    Display WireGuard tunnel status.

    Equivalent to show_status() in cs-wg.sh.
    """
    # Load saved codespace name
    cs_name = config.codespace_name or os.environ.get('CODESPACE_NAME', '')
    if not cs_name:
        cs_file = config.config_dir / 'current_codespace'
        if cs_file.exists():
            for line in cs_file.read_text().splitlines():
                m = re.match(r'CODESPACE_NAME="?([^"]+)"?', line)
                if m:
                    cs_name = m.group(1)
                    break

    print(f"\n=== cs-wg Status ===\n")

    # Check interface
    result = subprocess.run(['ip', 'link', 'show', WG_INTERFACE], capture_output=True)
    if result.returncode == 0:
        print(f"Interface:       {WG_INTERFACE} UP")
        result2 = subprocess.run(['wg', 'show', WG_INTERFACE], capture_output=True, text=True)
        if result2.returncode == 0:
            print()
            print(result2.stdout)
        else:
            print("  (need root for details)")
    else:
        print(f"Interface:       DOWN")

    print()
    print(f"Local IP:        {WG_LOCAL_IP}")
    print(f"Remote IP:       {WG_REMOTE_IP}")
    print(f"Codespace:       {cs_name or '<not set>'}")

    # Test connectivity if interface is up
    result = subprocess.run(['ip', 'link', 'show', WG_INTERFACE], capture_output=True)
    if result.returncode == 0:
        remote_host = WG_REMOTE_IP.split('/')[0]
        print()
        result = subprocess.run(['ping', '-c', '1', '-W', '2', remote_host], capture_output=True)
        if result.returncode == 0:
            print("Tunnel:          CONNECTED")

            # Test internet through tunnel
            remote_ip = None
            for url in ['https://api.ipify.org', 'https://ifconfig.me', 'https://icanhazip.com']:
                result = subprocess.run(
                    ['curl', '-4', '-s', '--interface', WG_INTERFACE,
                     '--connect-timeout', '5', url],
                    capture_output=True, text=True
                )
                if result.returncode == 0 and result.stdout.strip():
                    remote_ip = result.stdout.strip()
                    break
            print(f"Remote ext IP:   {remote_ip or 'N/A'}")
        else:
            print("Tunnel:          NO CONNECTIVITY")

    print()


def show_help() -> None:
    """
    Display cs-wg help text.

    Equivalent to show_help() in cs-wg.sh.
    """
    remote_host = WG_REMOTE_IP.split('/')[0]
    print(f"""cs-wg - WireGuard tunnel through GitHub Codespaces v{VERSION} (Python)

USAGE:
    sudo cs-wg <command> [options]

COMMANDS:
    up              Start WireGuard tunnel
    down            Stop WireGuard tunnel
    status          Show tunnel status

    route add <ip>  Route specific IP/CIDR through tunnel
    route del <ip>  Remove route
    route all       Route ALL traffic through tunnel
    route restore   Restore normal routing

    monitor [type]  Monitor tunnel traffic (requires tcpdump)
                    Types: http, dns, hosts, conns, all, leak

    help            Show this help

OPTIONS:
    -c, --codespace    Codespace name to use

EXAMPLES:
    # Start tunnel
    sudo cs-wg up

    # Check status
    sudo cs-wg status

    # Route specific target through tunnel
    sudo cs-wg route add 93.184.216.34
    sudo cs-wg route add example.com

    # Test
    curl --interface {WG_INTERFACE} https://ifconfig.me
    ping {remote_host}

    # Stop
    sudo cs-wg down

FILES:
    Keys & Config:  ~/.config/cs-proxy/wireguard/

NOTE:
    This requires root privileges for WireGuard interface management.
""")


def cmd_up(args, config: Config, gh: GitHubManager) -> int:
    """Start WireGuard tunnel."""
    start_tunnel(config, gh)
    return 0


def cmd_down(args, config: Config, gh: GitHubManager) -> int:
    """Stop WireGuard tunnel."""
    stop_tunnel(config, gh)
    return 0


def cmd_status(args, config: Config, gh: GitHubManager) -> int:
    """Show tunnel status."""
    show_status(config, gh)
    return 0


def cmd_route(args, config: Config, gh: GitHubManager) -> int:
    """Manage routing."""
    action = getattr(args, 'action', None)

    if action == 'all':
        route_all(config)
    elif action == 'restore':
        route_restore(config)
    elif action == 'add':
        network = getattr(args, 'network', None)
        if not network:
            get_logger().error("Usage: cs-wg route add <ip/cidr>")
            return 1
        _check_root()
        add_route(network)
    elif action in ('del', 'rm'):
        network = getattr(args, 'network', None)
        if not network:
            get_logger().error("Usage: cs-wg route del <ip/cidr>")
            return 1
        _check_root()
        del_route(network)
    else:
        get_logger().error("Usage: cs-wg route {add|del|all|restore}")
        return 1
    return 0


def cmd_monitor(args, config: Config, gh: GitHubManager) -> int:
    """Monitor WireGuard traffic."""
    mode = getattr(args, 'mode', None)
    monitor_traffic(mode)
    return 0


COMMANDS = {
    'up':      cmd_up,
    'down':    cmd_down,
    'status':  cmd_status,
    'route':   cmd_route,
    'monitor': cmd_monitor,
}
