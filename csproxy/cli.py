#!/usr/bin/env python3
"""
CLI entry points for cs-proxy toolkit.

Provides command-line interfaces for cs-proxy, cs-serve, cs-wg, and cs-tools.
Each main command has its own entry point.
"""

import subprocess
import sys

from .github import GitHubManager
from .utils import CSProxyError, Config, get_logger, setup_logger


def main_proxy(argv=None):
    """
    Entry point for cs-proxy command.

    Replaces cs-proxy.sh with full Python implementation.
    Handles global argument parsing and dispatches to subcommands.
    """
    import argparse
    from .proxy import COMMANDS, show_help

    # Parse global options (before the subcommand)
    parser = argparse.ArgumentParser(
        prog='cs-proxy',
        description='GitHub Codespaces Proxy Tool - SOCKS5/HTTP proxy management',
        add_help=False,
    )
    parser.add_argument('-p', '--port', type=int, help='SOCKS5 proxy port (default: 1080)')
    parser.add_argument('-n', '--num-proxies', type=int, default=1,
                        help='Number of codespaces to create (1-2, default: 1)')
    parser.add_argument('-c', '--codespace', help='Codespace name to use')
    parser.add_argument('-l', '--location', dest='locations',
                        action='append', metavar='REGION',
                        choices=['EastUs', 'WestUs2', 'WestEurope', 'SouthEastAsia'],
                        help='Region for new Codespace: EastUs, WestUs2, WestEurope, SouthEastAsia'
                             ' (repeat for multiple: -l WestEurope -l EastUs)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('-h', '--help', action='store_true', help='Show help and exit')
    parser.add_argument('command', nargs='?', default='help', help='Command to run')
    parser.add_argument('command_args', nargs='*', help='Command arguments')

    parsed, remaining = parser.parse_known_args(argv)
    command_args = (parsed.command_args or []) + remaining

    if parsed.help and not parsed.command:
        show_help()
        return 0

    logger = setup_logger(verbose=parsed.verbose)

    config = Config()
    config.ensure_dirs()

    if parsed.port:
        config.set('socks_port', parsed.port)
    config.set('num_proxies', parsed.num_proxies)
    if parsed.codespace:
        config.set('codespace_name', parsed.codespace)
    if parsed.locations:
        config.set('locations', parsed.locations)
    if parsed.verbose:
        config.set('verbose', True)

    gh = GitHubManager(config_dir=config.config_dir)

    cmd_name = parsed.command or 'help'

    if cmd_name not in COMMANDS:
        logger.error(f"Unknown command: {cmd_name}. Use 'cs-proxy help' for usage.")
        return 1

    try:
        return COMMANDS[cmd_name](command_args, config, gh) or 0

    except KeyboardInterrupt:
        print()
        logger.info("Interrupted by user")
        from .proxy import SSHTunnel
        SSHTunnel(config, config.codespace_name or '').stop()
        return 130

    except CSProxyError as e:
        logger.error(str(e))
        return e.exit_code

    except SystemExit as e:
        return int(e.code) if e.code is not None else 0

    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(e.cmd)}")
        if e.stderr:
            logger.error(e.stderr.strip())
        if config.verbose:
            import traceback
            traceback.print_exc()
        return 1

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        if config.verbose:
            import traceback
            traceback.print_exc()
        return 1


def main_serve(argv=None):
    """
    Entry point for cs-serve command.

    Replaces cs-serve.sh with Python implementation.
    Handles file serving, directory listing, redirects, and custom responses.
    """
    import argparse

    logger = setup_logger()

    parser = argparse.ArgumentParser(
        prog='cs-serve',
        description='GitHub Codespaces File Server - serve files with public URLs',
    )
    parser.add_argument('-c', '--codespace', help='Codespace name to use')
    parser.add_argument('-d', '--domain', help='Custom domain via Cloudflare Worker')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')

    subparsers = parser.add_subparsers(dest='command', help='Serve mode')

    sp_file = subparsers.add_parser('file', help='Serve a single file')
    sp_file.add_argument('filepath', help='Path to file to serve')
    sp_file.add_argument('port', nargs='?', type=int, default=9999, help='Port (default: 9999)')

    sp_dir = subparsers.add_parser('dir', help='Serve a directory with file listing')
    sp_dir.add_argument('directory', help='Directory to serve')
    sp_dir.add_argument('port', nargs='?', type=int, default=9999, help='Port (default: 9999)')

    sp_redir = subparsers.add_parser('redirect', help='HTTP redirect server')
    sp_redir.add_argument('target_url', help='URL to redirect to')
    sp_redir.add_argument('port', nargs='?', type=int, default=9999, help='Port (default: 9999)')
    sp_redir.add_argument('code', nargs='?', type=int, default=302, help='HTTP redirect code (default: 302)')

    sp_custom = subparsers.add_parser('custom', help='Custom HTTP response server')
    sp_custom.add_argument('port', type=int, help='Port to listen on')
    sp_custom.add_argument('body', help='Response body')
    sp_custom.add_argument('content_type', nargs='?', default='text/plain', help='Content-Type')
    sp_custom.add_argument('status', nargs='?', type=int, default=200, help='HTTP status code')

    sp_capture = subparsers.add_parser('capture', help='Capture and log POST data')
    sp_capture.add_argument('port', nargs='?', type=int, default=9999, help='Port (default: 9999)')

    sp_stop = subparsers.add_parser('stop', help='Stop server on a port')
    sp_stop.add_argument('port', nargs='?', type=int, default=9999, help='Port (default: 9999)')

    subparsers.add_parser('clean', help='Kill all servers and port forwards')
    subparsers.add_parser('cleanup', help='Kill all servers and port forwards (alias)')
    subparsers.add_parser('list', help='List files on Codespace')

    args = parser.parse_args(argv)

    if args.verbose:
        logger = setup_logger(verbose=True)

    if not args.command:
        parser.print_help()
        return 1

    try:
        from .serve import SERVE_COMMANDS
        config = Config()
        if args.codespace:
            config.set('codespace_name', args.codespace)
        gh = GitHubManager(config_dir=config.config_dir)
        handler = SERVE_COMMANDS.get(args.command)
        if handler:
            return handler(args, config, gh) or 0
        logger.error(f"Unknown serve command: {args.command}")
        return 1

    except CSProxyError as e:
        logger.error(str(e))
        return e.exit_code

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130


def main_wg(argv=None):
    """
    Entry point for cs-wg command.

    Replaces cs-wg.sh with Python implementation.
    Manages WireGuard VPN tunnels through Codespaces.
    """
    import argparse

    logger = setup_logger()

    parser = argparse.ArgumentParser(
        prog='cs-wg',
        description='GitHub Codespaces WireGuard VPN - full transparent tunneling',
    )
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')

    subparsers = parser.add_subparsers(dest='command', help='WireGuard command')

    subparsers.add_parser('up', help='Start WireGuard tunnel')
    subparsers.add_parser('down', help='Stop WireGuard tunnel')
    subparsers.add_parser('status', help='Show tunnel status')

    sp_route = subparsers.add_parser('route', help='Routing management')
    sp_route.add_argument('action', choices=['all', 'restore', 'add', 'del'])
    sp_route.add_argument('network', nargs='?', help='Network CIDR (for add/del)')

    sp_monitor = subparsers.add_parser('monitor', help='Traffic monitoring')
    sp_monitor.add_argument(
        'mode', nargs='?',
        choices=['http', 'dns', 'hosts', 'conns', 'leak'],
        default=None,
    )

    args = parser.parse_args(argv)

    if args.verbose:
        logger = setup_logger(verbose=True)

    if not args.command:
        parser.print_help()
        return 1

    try:
        from .wireguard import COMMANDS as WG_COMMANDS
        config = Config()
        gh = GitHubManager(config_dir=config.config_dir)
        handler = WG_COMMANDS.get(args.command)
        if handler:
            return handler(args, config, gh) or 0
        logger.error(f"Unknown wg command: {args.command}")
        return 1

    except CSProxyError as e:
        logger.error(str(e))
        return e.exit_code

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130


if __name__ == '__main__':
    sys.exit(main_proxy())
