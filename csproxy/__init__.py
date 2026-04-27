#!/usr/bin/env python3
"""
cs-proxy - GitHub Codespaces Proxy Toolkit

Transform GitHub Codespaces into powerful SOCKS5 proxies, file servers,
and WireGuard VPN tunnels for security research and testing.
"""

__version__ = "1.0.0"
__author__ = "cs-proxy contributors"
__license__ = "Apache-2.0"

from .github import GitHubManager
from .codespace import CodespaceSelector
from .proxy import ProxychainsConfig
from .state import State
from .tunnel import HTTPProxyManager, SSHTunnel
from .tools import (
    check_proxy,
    ipcheck,
    pcurl,
    pcs,
    pffuf,
    phttpx,
    pnmap,
    pnuclei,
    pportscan,
    psqlmap,
    psub,
    pwget,
)
from .utils import (
    CSProxyError,
    Config,
    check_dependencies,
    get_logger,
    setup_logger,
)

__all__ = [
    '__version__',
    # Core managers
    'GitHubManager',
    'SSHTunnel',
    'HTTPProxyManager',
    'CodespaceSelector',
    'ProxychainsConfig',
    'State',
    # Proxied tool wrappers
    'check_proxy',
    'ipcheck',
    'pcurl',
    'pwget',
    'pnmap',
    'pnuclei',
    'pffuf',
    'phttpx',
    'psqlmap',
    'pcs',
    'psub',
    'pportscan',
    # Utilities
    'Config',
    'setup_logger',
    'get_logger',
    'check_dependencies',
    'CSProxyError',
]
