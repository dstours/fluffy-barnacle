#!/usr/bin/env python3
"""
FastMCP server wrapping the csproxy service layer.

This module is a thin MCP front-end: every tool delegates to ``csproxy.services``
(the presentation-free, structured-data API) or to ``GitHubManager``. No core
logic is reimplemented here, so behaviour stays identical across the CLI, the
TUI, and MCP. Service functions return plain data and raise on error; FastMCP
turns a raised exception into an MCP tool error, so the wrappers stay tiny.

Transport is stdio only (local, single-client). The toolkit provisions real
GitHub Codespaces infrastructure under GitHub's Codespaces Terms of Service, so
destructive tools (`delete_codespace`, `stop_all_tunnels`, `stop_chain`,
`delete_chain`) are clearly marked in their docstrings; well-behaved MCP clients
surface those descriptions and confirm before calling.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..github import GitHubManager
from ..utils import Config
from .. import services


def _context() -> tuple[Config, GitHubManager]:
    """Build a fresh Config + GitHubManager, mirroring the CLI entry points.

    Built per call rather than cached so each tool invocation sees current
    on-disk config/state (the CLI and TUI may mutate it between calls) and so a
    transient failure never leaves a poisoned singleton behind.
    """
    config = Config()
    config.ensure_dirs()
    gh = GitHubManager(config_dir=config.config_dir)
    return config, gh


def build_server() -> FastMCP:
    """Construct the FastMCP server with all tools and resources registered."""
    mcp = FastMCP("cs-mcp")

    # ----------------------------------------------------------------- reads
    @mcp.tool()
    def diagnostics() -> list[dict]:
        """Run dependency/configuration health checks (the `cs-proxy check` set).

        Returns a list of {status: "PASS"|"FAIL", message} entries.
        """
        config, gh = _context()
        return [asdict(c) for c in services.run_diagnostics(config, gh)]

    @mcp.tool()
    def list_pool(reconcile: bool = True) -> list[dict]:
        """List tracked SSH proxy tunnels from the state store.

        Set reconcile=True (default) to mark dead-PID tunnels crashed first so
        statuses are fresh. Each entry carries id/kind/port/pid/status/
        codespace_name/failures.
        """
        config, _ = _context()
        return services.list_pool(config, reconcile=reconcile)

    @mcp.tool()
    def list_codespaces() -> list[dict]:
        """List the authenticated user's GitHub Codespaces (best effort).

        Returns [] rather than erroring if gh is missing or unauthenticated.
        """
        _, gh = _context()
        return services.list_codespaces_safe(gh)

    @mcp.tool()
    def get_codespace(name: str) -> Optional[dict]:
        """Get a single Codespace by name, or null if it does not exist."""
        _, gh = _context()
        return gh.get_codespace(name)

    @mcp.tool()
    def get_logs(lines: int = 50) -> list[str]:
        """Return the last `lines` lines of the proxy log ([] if none)."""
        config, _ = _context()
        return services.get_logs(config, lines=lines)

    @mcp.tool()
    def list_chains() -> list[dict]:
        """List two-hop Codespace chains (defined + running, combined view)."""
        config, _ = _context()
        return services.list_chains(config)

    # ------------------------------------------------------- tunnel actions
    @mcp.tool()
    def stop_tunnel(port: int) -> str:
        """Stop the SSH tunnel bound to `port` and remove it from the pool."""
        config, _ = _context()
        services.stop_tunnel(config, port)
        return f"Stopped tunnel on port {port}"

    @mcp.tool()
    def drain_tunnel(port: int) -> str:
        """Mark the tunnel on `port` as draining (stops taking new traffic)."""
        config, _ = _context()
        services.drain_tunnel(config, port)
        return f"Tunnel on port {port} marked draining"

    @mcp.tool()
    def rotate_pool() -> int:
        """Return a random healthy tunnel port. Errors if none are healthy."""
        config, _ = _context()
        return services.rotate_pool(config)

    @mcp.tool()
    def stop_all_tunnels() -> str:
        """DESTRUCTIVE. Stop the primary tunnel, all pool tunnels, and the HTTP
        proxy. Tears down all local proxy forwarding at once."""
        config, _ = _context()
        services.stop_all_tunnels(config)
        return "Stopped all tunnels and the HTTP proxy"

    # -------------------------------------------------------- chain actions
    @mcp.tool()
    def start_chain(name: str, port: Optional[int] = None) -> str:
        """Start a defined two-hop chain. Slow: provisions/links two hops."""
        config, gh = _context()
        services.start_chain(config, gh, name, port=port)
        return f"Started chain {name}"

    @mcp.tool()
    def stop_chain(name: str) -> str:
        """DESTRUCTIVE. Stop a running chain and clean up its remote relays."""
        config, gh = _context()
        services.stop_chain(config, gh, name)
        return f"Stopped chain {name}"

    @mcp.tool()
    def delete_chain(name: str) -> str:
        """DESTRUCTIVE. Remove a chain definition from config. Errors if unknown."""
        config, _ = _context()
        services.delete_chain(config, name)
        return f"Deleted chain definition {name}"

    # ----------------------------------------------------- codespace actions
    @mcp.tool()
    def create_codespace(repo: Optional[str] = None, machine: str = "basicLinux32gb") -> dict:
        """Create a new GitHub Codespace (provisions real, billable infra).

        repo defaults to ``github/codespaces-blank`` (GitHub's blank template — a
        generic Ubuntu Codespace, which is what the SOCKS relay wants and works
        with no local repo). machine defaults to the smallest standard Linux
        machine; pass "" only with a TTY. Returns {"name": <new codespace name>}.
        """
        _, gh = _context()
        return gh.create_codespace(repo=repo, machine=machine)

    @mcp.tool()
    def delete_codespace(name: str, force: bool = False) -> str:
        """DESTRUCTIVE. Permanently delete a Codespace. Set force=True to skip
        gh's confirmation prompt (required when running non-interactively)."""
        _, gh = _context()
        gh.delete_codespace(name, force=force)
        return f"Deleted codespace {name}"

    @mcp.tool()
    def start_codespace(name: str) -> str:
        """Start a stopped Codespace."""
        _, gh = _context()
        gh.start_codespace(name)
        return f"Started codespace {name}"

    @mcp.tool()
    def stop_codespace(name: str) -> str:
        """Stop a running Codespace (preserves it; does not delete)."""
        _, gh = _context()
        gh.stop_codespace(name)
        return f"Stopped codespace {name}"

    # ------------------------------------------------------------ resources
    @mcp.resource("cs://pool")
    def pool_resource() -> list[dict]:
        """Current SSH tunnel pool (reconciled), as a readable resource."""
        config, _ = _context()
        return services.list_pool(config, reconcile=True)

    @mcp.resource("cs://codespaces")
    def codespaces_resource() -> list[dict]:
        """Current GitHub Codespaces (best effort), as a readable resource."""
        _, gh = _context()
        return services.list_codespaces_safe(gh)

    return mcp


def run_server(argv=None) -> int:
    """Parse args and run the MCP server over stdio."""
    parser = argparse.ArgumentParser(
        prog="cs-mcp",
        description="MCP server exposing the csproxy toolkit to MCP-aware clients (stdio).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args(argv)

    # Log to stderr only -- stdout is the MCP stdio transport and must stay
    # clean. csproxy.setup_logger() hardcodes a stdout handler and no-ops once
    # the logger already has handlers, so we install a stderr handler first to
    # win that race and keep stdout pristine.
    logger = logging.getLogger("csproxy")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)

    build_server().run(transport="stdio")
    return 0
