#!/usr/bin/env python3
"""
Named GitHub account configuration.

Accounts let future chain/pool features operate against multiple GitHub
identities without passing PATs around as command-line arguments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .utils.errors import ConfigError


@dataclass(frozen=True)
class GitHubAccount:
    """A named GitHub account backed by an environment variable token."""

    name: str
    token_env: str = "GH_TOKEN"
    gh_host: str = "github.com"

    @property
    def token(self) -> Optional[str]:
        """Return the configured token, if present in the environment."""
        return os.environ.get(self.token_env)

    def require_token(self) -> str:
        """Return the token or raise a config error with a safe message."""
        token = self.token
        if not token:
            raise ConfigError(
                f"Account '{self.name}' requires ${self.token_env} to be set"
            )
        return token

    @classmethod
    def from_config(cls, config, name: str) -> "GitHubAccount":
        """Load a named account from Config.accounts."""
        accounts = config.get("accounts", {})
        raw = accounts.get(name)
        if not isinstance(raw, dict):
            raise ConfigError(f"Unknown account: {name}")
        token_env = raw.get("token_env")
        if not token_env:
            raise ConfigError(f"Account '{name}' is missing token_env")
        return cls(
            name=name,
            token_env=token_env,
            gh_host=raw.get("gh_host", "github.com"),
        )


def default_account() -> GitHubAccount:
    """Return the default account that follows gh/GH_TOKEN conventions."""
    return GitHubAccount(name="default", token_env="GH_TOKEN")
