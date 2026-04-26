#!/usr/bin/env python3
"""
Shared WireGuard constants to avoid duplication across modules.

All WireGuard-related modules should import from here instead of
redefining defaults locally.
"""

import os

WG_INTERFACE = os.environ.get("WG_INTERFACE", "cswg0")
WG_PORT = int(os.environ.get("WG_PORT", "51820"))
WG_LOCAL_IP = os.environ.get("WG_LOCAL_IP", "10.99.99.2/24")
WG_REMOTE_IP = os.environ.get("WG_REMOTE_IP", "10.99.99.1/24")
WG_NETWORK = os.environ.get("WG_NETWORK", "10.99.99.0/24")
TCP_RELAY_PORT = 51821
